import sys
from unittest.mock import patch

from utils import sandbox_runner


def _run_python_program(program, expected_output=''):
    with patch.object(sandbox_runner, '_find_compiler', return_value=None):
        return sandbox_runner._run_single_test_command(
            [sys.executable, '-c', program],
            input_data='',
            expected_output=expected_output,
            work_dir='.',
        )


def test_normal_output_keeps_existing_comparison_behavior():
    result = _run_python_program(
        "import sys; sys.stdout.write('answer\\n')",
        expected_output='answer',
    )

    assert result['passed'] is True
    assert sandbox_runner._normalize_output(result['actual_output']) == 'answer'
    assert result['termination_reason'] is None


def test_stdout_limit_terminates_process_and_cannot_pass():
    with patch.object(sandbox_runner, 'MAX_OUTPUT_LEN', 64):
        result = _run_python_program(
            "import sys; sys.stdout.write('x' * 256); sys.stdout.flush()",
            expected_output='x' * 64,
        )

    assert result['passed'] is False
    assert result['termination_reason'] == 'stdout_limit'
    assert len(result['actual_output'].encode('utf-8')) == 64
    assert '超过限制' in result['error']


def test_stderr_limit_terminates_process_and_cannot_pass():
    with patch.object(sandbox_runner, 'MAX_OUTPUT_LEN', 64):
        result = _run_python_program(
            "import sys; sys.stderr.write('e' * 256); sys.stderr.flush()",
            expected_output='',
        )

    assert result['passed'] is False
    assert result['termination_reason'] == 'stderr_limit'
    assert '标准错误输出超过限制' in result['error']


def test_runtime_error_remains_a_failed_result_with_stderr_detail():
    result = _run_python_program(
        "import sys; sys.stderr.write('boom'); sys.exit(7)",
        expected_output='',
    )

    assert result['passed'] is False
    assert result['termination_reason'] == 'runtime_error'
    assert '退出码 7' in result['error']
    assert 'boom' in result['error']


def test_timeout_terminates_process_and_cannot_pass():
    with patch.object(sandbox_runner, 'RUN_TIMEOUT', 0.1):
        result = _run_python_program(
            'import time; time.sleep(1)',
            expected_output='',
        )

    assert result['passed'] is False
    assert result['termination_reason'] == 'timeout'
    assert '运行超时' in result['error']
