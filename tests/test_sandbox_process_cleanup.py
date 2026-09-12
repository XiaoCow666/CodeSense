import os
import pathlib
import sys
import time

from utils import sandbox_runner


def _run_program(program, work_dir, timeout=0.1):
    return sandbox_runner._run_bounded_process(
        [sys.executable, '-c', program],
        input_data='',
        work_dir=str(work_dir),
        env=os.environ.copy(),
        timeout=timeout,
    )


def test_timeout_terminates_descendant_processes(tmp_path):
    marker = pathlib.Path(tmp_path) / 'descendant-survived'
    descendant = (
        "import pathlib,time; time.sleep(0.4); "
        f"pathlib.Path({str(marker)!r}).write_text('alive', encoding='utf-8')"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); time.sleep(30)"
    )

    result = _run_program(parent, tmp_path)
    time.sleep(0.6)

    assert result['reason'] == 'timeout'
    assert not marker.exists()


def test_timeout_cleanup_preserves_next_normal_run(tmp_path):
    timed_out = _run_program('import time; time.sleep(30)', tmp_path)
    recovered = _run_program("import sys; sys.stdout.write('ok\\n')", tmp_path)

    assert timed_out['reason'] == 'timeout'
    assert recovered['reason'] is None
    assert recovered['returncode'] == 0
    assert sandbox_runner._normalize_output(recovered['stdout']) == 'ok'
