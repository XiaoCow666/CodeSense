"""
沙箱代码执行引擎
在受限环境中编译并运行 C++ 代码，对比测试用例输出。
依赖：系统已安装 g++ (MinGW on Windows / g++ on Linux)
"""
import os
import json
import subprocess
import tempfile
import platform
import re
import threading
import time
from typing import Any, Dict, List, Tuple

# 超时时间（秒）
COMPILE_TIMEOUT = 15
RUN_TIMEOUT = 5

# stdout/stderr 运行期间的读取上限（字节）。
MAX_OUTPUT_LEN = 4096
_READ_CHUNK_SIZE = 4096
_MAX_ERROR_DETAIL_LEN = 500


def _normalize_output(s: str) -> str:
    """标准化输出：统一换行符、去除行尾空白、去除末尾空行"""
    s = s.replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip() for line in s.split('\n')]
    # 去除末尾空行
    while lines and lines[-1] == '':
        lines.pop()
    return '\n'.join(lines)


def _find_compiler() -> str:
    """查找系统中可用的 C++ 编译器"""
    candidates = ['g++', 'g++.exe', 'c++']
    # Windows 常见 MinGW 路径
    windows_paths = [
        r'C:\MinGW\bin\g++.exe',
        r'C:\mingw64\bin\g++.exe',
        r'C:\Program Files\mingw-w64\x86_64-8.1.0-posix-seh-rt_v6-rev0\mingw64\bin\g++.exe',
        r'C:\msys64\mingw64\bin\g++.exe',
        r'C:\msys64\ucrt64\bin\g++.exe',
        # Anaconda/Miniconda 路径
        os.path.join(os.environ.get('CONDA_PREFIX', ''), 'Library', 'mingw-w64', 'bin', 'g++.exe'),
        os.path.join(os.environ.get('CONDA_PREFIX', ''), 'Library', 'bin', 'g++.exe'),
        # 用户可能安装在 E 盘
        r'E:\anaconda\Library\mingw-w64\bin\g++.exe',
        r'E:\anaconda\envs\student-eval\Library\mingw-w64\bin\g++.exe',
    ]
    if platform.system() == 'Windows':
        for path in windows_paths:
            if os.path.isfile(path):
                return path
    for cmd in candidates:
        try:
            result = subprocess.run(
                [cmd, '--version'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if result.returncode == 0:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


class _BoundedPipeReader(threading.Thread):
    """Read one subprocess pipe without allowing it to grow unboundedly."""

    def __init__(self, stream, limit: int, name: str):
        super().__init__(name=name, daemon=True)
        self.stream = stream
        self.limit = limit
        self.data = bytearray()
        self.exceeded = False
        self.error = None
        self.finished = threading.Event()

    def run(self):
        try:
            while True:
                remaining = self.limit - len(self.data)
                # Read one extra byte once the limit is reached so an exact
                # limit remains valid while the next byte is detected.
                read_size = max(1, min(_READ_CHUNK_SIZE, remaining + 1))
                read_method = getattr(self.stream, 'read1', self.stream.read)
                chunk = read_method(read_size)
                if not chunk:
                    break

                if isinstance(chunk, str):
                    chunk = chunk.encode('utf-8', errors='replace')

                if len(chunk) > remaining:
                    if remaining > 0:
                        self.data.extend(chunk[:remaining])
                    self.exceeded = True
                    break

                self.data.extend(chunk)
        except Exception as exc:
            self.error = exc
        finally:
            self.finished.set()


def _close_pipe(stream) -> None:
    if stream is None:
        return
    try:
        stream.close()
    except Exception:
        pass


def _terminate_process(process) -> None:
    """Terminate a direct child process and wait briefly for it to exit."""

    try:
        if process.poll() is None:
            process.kill()
    except (OSError, ProcessLookupError):
        pass

    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _decode_output(data: bytearray) -> str:
    return bytes(data).decode('utf-8', errors='replace')


def _run_bounded_process(
    command: List[str],
    input_data: str,
    work_dir: str,
    env: Dict[str, str],
    timeout: float,
) -> Dict[str, Any]:
    """Run a child process with bounded stdout/stderr readers.

    The returned ``reason`` is one of ``stdout_limit``, ``stderr_limit``,
    ``timeout``, ``launch_error``, ``read_error`` or ``None``. A limit breach
    is detected while the child is running and is never treated as a normal
    process completion.
    """

    started_at = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=work_dir,
            env=env,
        )
    except Exception as exc:
        return {
            'returncode': None,
            'stdout': '',
            'stderr': '',
            'reason': 'launch_error',
            'error': str(exc),
            'time_ms': int((time.monotonic() - started_at) * 1000),
        }

    stdout_reader = _BoundedPipeReader(
        process.stdout, MAX_OUTPUT_LEN, 'sandbox-stdout-reader'
    )
    stderr_reader = _BoundedPipeReader(
        process.stderr, MAX_OUTPUT_LEN, 'sandbox-stderr-reader'
    )

    def write_input():
        try:
            if process.stdin is not None:
                encoded_input = (input_data or '').encode('utf-8')
                if encoded_input:
                    process.stdin.write(encoded_input)
                    process.stdin.flush()
        except (BrokenPipeError, OSError):
            # The child may exit before consuming all input. Its exit status
            # is handled by the main process path below.
            pass
        finally:
            _close_pipe(process.stdin)

    input_writer = threading.Thread(
        target=write_input,
        name='sandbox-stdin-writer',
        daemon=True,
    )
    stdout_reader.start()
    stderr_reader.start()
    input_writer.start()

    timed_out = False
    try:
        while process.poll() is None:
            if stdout_reader.exceeded or stderr_reader.exceeded:
                break
            if time.monotonic() - started_at >= timeout:
                timed_out = True
                break
            time.sleep(0.005)
    finally:
        if timed_out or stdout_reader.exceeded or stderr_reader.exceeded:
            _terminate_process(process)
        else:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate_process(process)

        _close_pipe(process.stdin)
        input_writer.join(timeout=1)

        for reader in (stdout_reader, stderr_reader):
            reader.join(timeout=1)
            if not reader.finished.is_set():
                _close_pipe(reader.stream)
                reader.join(timeout=0.2)

        _close_pipe(process.stdout)
        _close_pipe(process.stderr)

    reason = None
    if stdout_reader.exceeded:
        reason = 'stdout_limit'
    elif stderr_reader.exceeded:
        reason = 'stderr_limit'
    elif timed_out:
        reason = 'timeout'
    elif stdout_reader.error or stderr_reader.error:
        reason = 'read_error'

    return {
        'returncode': process.returncode,
        'stdout': _decode_output(stdout_reader.data),
        'stderr': _decode_output(stderr_reader.data),
        'reason': reason,
        'error': stdout_reader.error or stderr_reader.error,
        'time_ms': int((time.monotonic() - started_at) * 1000),
    }


def compile_cpp(source_code: str, work_dir: str) -> Tuple[bool, str, str]:
    """
    编译 C++ 源码。
    返回 (success, exe_path, error_message)
    """
    compiler = _find_compiler()
    if not compiler:
        return False, '', '系统未安装 C++ 编译器（g++），无法运行测试用例。请联系管理员安装 MinGW/g++。'

    src_path = os.path.join(work_dir, 'solution.cpp')
    exe_path = os.path.join(work_dir, 'solution.exe' if platform.system() == 'Windows' else 'solution')

    with open(src_path, 'w', encoding='utf-8') as f:
        f.write(source_code)

    try:
        # 注入编译器目录到 PATH，解决 Windows 下 DLL 缺失问题
        env = os.environ.copy()
        compiler_dir = os.path.dirname(compiler)
        env['PATH'] = compiler_dir + os.pathsep + env.get('PATH', '')

        completed = _run_bounded_process(
            [compiler, src_path, '-o', exe_path, '-std=c++17', '-O2', '-Wall'],
            input_data='',
            work_dir=work_dir,
            env=env,
            timeout=COMPILE_TIMEOUT,
        )

        if completed['reason'] == 'timeout':
            return False, '', f'编译超时（超过 {COMPILE_TIMEOUT} 秒）'
        if completed['reason'] in ('stdout_limit', 'stderr_limit'):
            stream_name = 'stdout' if completed['reason'] == 'stdout_limit' else 'stderr'
            return False, '', f'编译器 {stream_name} 输出超过限制（{MAX_OUTPUT_LEN} 字节），已终止编译进程'
        if completed['reason']:
            return False, '', f'编译过程出错：{completed["error"] or completed["reason"]}'
        if completed['returncode'] != 0:
            err = completed['stderr'][:2000] if completed['stderr'] else '编译失败（无错误信息）'
            return False, '', err
        return True, exe_path, ''
    except Exception as e:
        return False, '', f'编译过程出错：{str(e)}'


def _run_single_test_command(
    command: List[str],
    input_data: str,
    expected_output: str,
    work_dir: str,
) -> Dict:
    """
    运行单个测试用例。
    返回结果字典：{passed, actual_output, expected_output, error, time_ms}
    """
    result = {
        'passed': False,
        'actual_output': '',
        'expected_output': expected_output,
        'error': None,
        'time_ms': 0,
        'termination_reason': None,
    }
    try:
        # 运行编译后的程序（同样注入 PATH，解决运行时 DLL 依赖问题）
        env = os.environ.copy()
        compiler = _find_compiler()
        if compiler:
            env['PATH'] = os.path.dirname(compiler) + os.pathsep + env.get('PATH', '')

        completed = _run_bounded_process(
            command,
            input_data=input_data,
            work_dir=work_dir,
            env=env,
            timeout=RUN_TIMEOUT,
        )
        result['time_ms'] = completed['time_ms']
        result['actual_output'] = completed['stdout']

        if completed['reason'] == 'stdout_limit':
            result['termination_reason'] = 'stdout_limit'
            result['error'] = f'标准输出超过限制（{MAX_OUTPUT_LEN} 字节），已终止运行进程'
            return result
        if completed['reason'] == 'stderr_limit':
            result['termination_reason'] = 'stderr_limit'
            result['error'] = f'标准错误输出超过限制（{MAX_OUTPUT_LEN} 字节），已终止运行进程'
            return result
        if completed['reason'] == 'timeout':
            result['termination_reason'] = 'timeout'
            result['error'] = f'运行超时（超过 {RUN_TIMEOUT} 秒）'
            return result
        if completed['reason']:
            result['termination_reason'] = completed['reason']
            result['error'] = f'运行出错：{completed["error"] or completed["reason"]}'
            return result

        if completed['returncode'] != 0:
            result['termination_reason'] = 'runtime_error'
            stderr = completed['stderr'][:_MAX_ERROR_DETAIL_LEN] if completed['stderr'] else ''
            result['error'] = f'程序运行时错误（退出码 {completed["returncode"]}）' + (f'：{stderr}' if stderr else '')
            return result

        # 比较输出（标准化后）
        if _normalize_output(completed['stdout']) == _normalize_output(expected_output):
            result['passed'] = True
        return result

    except Exception as e:
        result['termination_reason'] = 'launch_error'
        result['error'] = f'运行出错：{str(e)}'
        return result


def run_single_test(exe_path: str, input_data: str, expected_output: str, work_dir: str) -> Dict:
    """
    运行单个测试用例。
    返回结果字典：{passed, actual_output, expected_output, error, time_ms}
    """
    return _run_single_test_command(
        [exe_path],
        input_data=input_data,
        expected_output=expected_output,
        work_dir=work_dir,
    )


def run_test_cases(source_code: str, test_cases: List[Dict]) -> Dict:
    """
    主入口：编译并对所有测试用例运行代码。

    参数：
        source_code: C++ 源代码字符串
        test_cases: list of {'input_data': str, 'expected_output': str, 'id': int, 'is_public': bool}

    返回：
        {
            'compiler_available': bool,
            'compile_success': bool,
            'compile_error': str,
            'passed': int,
            'total': int,
            'status': 'passed'|'partial'|'failed'|'compile_error'|'no_cases'|'unavailable',
            'details': [per-case result dicts],
        }
    """
    if not test_cases:
        return {
            'compiler_available': True,
            'compile_success': False,
            'compile_error': '',
            'passed': 0,
            'total': 0,
            'status': 'no_cases',
            'details': [],
        }

    with tempfile.TemporaryDirectory() as work_dir:
        # 编译
        ok, exe_path, compile_err = compile_cpp(source_code, work_dir)

        if '系统未安装' in compile_err or not _find_compiler():
            return {
                'compiler_available': False,
                'compile_success': False,
                'compile_error': compile_err,
                'passed': 0,
                'total': len(test_cases),
                'status': 'unavailable',
                'details': [],
            }

        if not ok:
            return {
                'compiler_available': True,
                'compile_success': False,
                'compile_error': compile_err,
                'passed': 0,
                'total': len(test_cases),
                'status': 'compile_error',
                'details': [],
            }

        # 运行每个测试用例
        details = []
        passed = 0
        for idx, tc in enumerate(test_cases):
            res = run_single_test(
                exe_path,
                tc.get('input_data', ''),
                tc.get('expected_output', ''),
                work_dir
            )
            res['case_id'] = tc.get('id', idx + 1)
            res['is_public'] = tc.get('is_public', False)
            res['order_index'] = idx + 1
            if res['passed']:
                passed += 1
            details.append(res)

        total = len(test_cases)
        if passed == total:
            status = 'passed'
        elif passed == 0:
            status = 'failed'
        else:
            status = 'partial'

        return {
            'compiler_available': True,
            'compile_success': True,
            'compile_error': '',
            'passed': passed,
            'total': total,
            'status': status,
            'details': details,
        }
