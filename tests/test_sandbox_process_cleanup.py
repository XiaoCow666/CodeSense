import os
import pathlib
import signal
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from utils import sandbox_runner


def _run_program(program, work_dir, timeout=0.1):
    return sandbox_runner._run_bounded_process(
        [sys.executable, '-c', program],
        input_data='',
        work_dir=str(work_dir),
        env=os.environ.copy(),
        timeout=timeout,
    )


def _cleanup_descendant(pid_file):
    if not pid_file.exists():
        return
    pid = int(pid_file.read_text(encoding='utf-8'))
    if os.name == 'nt':
        subprocess.run(
            ['taskkill', '/PID', str(pid), '/T', '/F'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _descendant_program(pid_file, marker, delay=0.4):
    descendant = (
        "import os,pathlib,time; "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8'); "
        f"time.sleep({delay}); "
        f"pathlib.Path({str(marker)!r}).write_text('alive', encoding='utf-8'); "
        "time.sleep(5)"
    )
    return descendant


def test_timeout_terminates_descendant_processes(tmp_path):
    pid_file = pathlib.Path(tmp_path) / 'grandchild.pid'
    marker = pathlib.Path(tmp_path) / 'descendant-survived'
    descendant = _descendant_program(pid_file, marker)
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); time.sleep(30)"
    )

    try:
        result = _run_program(parent, tmp_path)
        time.sleep(0.6)

        assert result['reason'] == 'timeout'
        assert not marker.exists()
    finally:
        _cleanup_descendant(pid_file)


def test_normal_exit_terminates_descendant_processes(tmp_path):
    pid_file = pathlib.Path(tmp_path) / 'grandchild.pid'
    marker = pathlib.Path(tmp_path) / 'descendant-survived'
    descendant = _descendant_program(pid_file, marker)
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); time.sleep(0.05)"
    )

    try:
        result = _run_program(parent, tmp_path, timeout=1)
        time.sleep(0.6)

        assert result['reason'] is None
        assert result['returncode'] == 0
        assert not marker.exists()
    finally:
        _cleanup_descendant(pid_file)


def test_output_limit_terminates_descendant_processes(tmp_path):
    pid_file = pathlib.Path(tmp_path) / 'grandchild.pid'
    marker = pathlib.Path(tmp_path) / 'descendant-survived'
    descendant = _descendant_program(pid_file, marker)
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); "
        "sys.stdout.write('x' * 256); sys.stdout.flush(); time.sleep(30)"
    )

    try:
        with patch.object(sandbox_runner, 'MAX_OUTPUT_LEN', 64):
            result = _run_program(parent, tmp_path, timeout=1)
        time.sleep(0.6)

        assert result['reason'] == 'stdout_limit'
        assert not marker.exists()
    finally:
        _cleanup_descendant(pid_file)


def test_timeout_cleanup_preserves_next_normal_run(tmp_path):
    timed_out = _run_program('import time; time.sleep(30)', tmp_path)
    recovered = _run_program("import sys; sys.stdout.write('ok\\n')", tmp_path)

    assert timed_out['reason'] == 'timeout'
    assert recovered['reason'] is None
    assert recovered['returncode'] == 0
    assert sandbox_runner._normalize_output(recovered['stdout']) == 'ok'


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job Object regression')
def test_immediate_descendant_is_created_only_after_job_attachment(tmp_path):
    pid_file = pathlib.Path(tmp_path) / 'grandchild.pid'
    marker = pathlib.Path(tmp_path) / 'descendant-survived'
    descendant = _descendant_program(pid_file, marker, delay=0.4)
    parent = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}])"
    )
    original_create_job = sandbox_runner._create_process_job

    def delayed_create_job(process):
        time.sleep(0.2)
        return original_create_job(process)

    try:
        with patch.object(
            sandbox_runner,
            '_create_process_job',
            side_effect=delayed_create_job,
        ):
            result = _run_program(parent, tmp_path, timeout=1)
        time.sleep(0.6)

        assert result['reason'] is None
        assert result['returncode'] == 0
        assert not marker.exists()
    finally:
        _cleanup_descendant(pid_file)


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job Object regression')
def test_job_setup_failure_stops_suspended_user_process(tmp_path):
    marker = pathlib.Path(tmp_path) / 'user-code-ran'
    parent = (
        "import pathlib,time; "
        f"pathlib.Path({str(marker)!r}).write_text('ran', encoding='utf-8'); "
        "time.sleep(30)"
    )
    captured = []
    real_popen = sandbox_runner.subprocess.Popen

    def capture_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        captured.append(process)
        return process

    with patch.object(sandbox_runner.subprocess, 'Popen', side_effect=capture_popen):
        with patch.object(sandbox_runner, '_create_process_job', return_value=None):
            result = _run_program(parent, tmp_path, timeout=1)

    time.sleep(0.4)

    assert result['reason'] == 'launch_error'
    assert 'Job Object' in result['error']
    assert not marker.exists()
    assert captured and captured[0].poll() is not None
    assert captured[0]._handle.closed
