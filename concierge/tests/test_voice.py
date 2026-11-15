import os
import stat
import sys

import pytest

from concierge.config import load_config
from concierge.voice import CommandTranscriber, TranscriptionError


def script(tmp_path, body):
    path = tmp_path / "transcribe"
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_the_command_gets_the_audio_as_a_file_and_its_stdout_is_the_transcript(tmp_path):
    command = script(tmp_path, "import sys; print('  ' + open(sys.argv[2], 'rb').read().decode() + ' ok \\n')")
    assert CommandTranscriber((command, "--file", "{audio}")).transcribe(b"approve it") == "approve it ok"


def test_the_path_is_appended_when_the_command_has_no_placeholder(tmp_path):
    command = script(tmp_path, "import sys; print(open(sys.argv[1], 'rb').read().decode())")
    assert CommandTranscriber((command,)).transcribe(b"hello") == "hello"


def test_the_audio_file_is_gone_afterwards(tmp_path):
    command = script(tmp_path, "import sys; print(sys.argv[1])")
    path = CommandTranscriber((command,)).transcribe(b"x")
    assert not os.path.exists(path)


def test_the_command_is_not_run_through_a_shell(tmp_path):
    command = script(tmp_path, "import sys; print(sys.argv[1])")
    assert CommandTranscriber((command, "a; touch pwned", "{audio}")).transcribe(b"x") == "a; touch pwned"
    assert not (tmp_path / "pwned").exists()


def test_a_failing_command_reports_its_last_line(tmp_path):
    command = script(tmp_path, "import sys; sys.stderr.write('boom\\nmodel missing\\n'); sys.exit(2)")
    with pytest.raises(TranscriptionError, match="model missing"):
        CommandTranscriber((command,)).transcribe(b"x")


def test_a_missing_command_is_a_transcription_error():
    with pytest.raises(TranscriptionError, match="not found"):
        CommandTranscriber(("/no/such/whisper",)).transcribe(b"x")


def test_a_command_that_runs_too_long_is_stopped(tmp_path):
    command = script(tmp_path, "import time; time.sleep(5)")
    with pytest.raises(TranscriptionError, match="took longer"):
        CommandTranscriber((command,), timeout_s=0.2).transcribe(b"x")


def test_the_config_lists_the_command_and_defaults_to_none(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"repos": {}, "transcribe_command": ["whisper-cli", "-f", "{audio}"]}')
    assert load_config(path).transcribe_command == ("whisper-cli", "-f", "{audio}")
    path.write_text('{"repos": {}}')
    assert load_config(path).transcribe_command == ()
