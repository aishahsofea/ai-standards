import sys
import time

from concierge.supervisor import result_line, spawn_local


def wait_for(process, seconds=10):
    deadline = time.time() + seconds
    while process.poll() is None and time.time() < deadline:
        time.sleep(0.02)
    return process.poll()


def test_output_is_read_from_the_log_after_exit(tmp_path):
    process = spawn_local([sys.executable, "-c", "print('hello')"], tmp_path, tmp_path / "logs" / "run.log")
    assert wait_for(process) == 0 and process.tail() == "hello\n"


def test_interrupt_reaches_the_whole_process_group(tmp_path):
    code = "import subprocess, sys; subprocess.run([sys.executable, '-c', 'import time; time.sleep(60)'])"
    process = spawn_local([sys.executable, "-c", code], tmp_path, tmp_path / "run.log")
    time.sleep(0.5)
    process.interrupt()
    assert wait_for(process) not in (None, 0)


def test_the_result_is_the_last_json_line_with_a_status():
    assert result_line('noise\n{"status": "waiting", "stage": "plan"}\n') == {"status": "waiting", "stage": "plan"}
    assert result_line('{"other": 1}\nplain\n') is None
