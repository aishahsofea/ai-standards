import os
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

AUDIO = "{audio}"
TRANSCRIBE_TIMEOUT_S = 120


class TranscriptionError(Exception):
    pass


class Transcriber(Protocol):
    def transcribe(self, audio: bytes) -> str: ...


class CommandTranscriber:
    """Runs a local command on the audio file and takes its stdout as the transcript; no shell, nothing leaves the machine."""

    def __init__(self, command: tuple[str, ...], timeout_s: float = TRANSCRIBE_TIMEOUT_S) -> None:
        self.command = command
        self.timeout_s = timeout_s

    def transcribe(self, audio: bytes) -> str:
        with tempfile.TemporaryDirectory(prefix="concierge-voice-") as folder:
            path = Path(folder) / "voice.ogg"
            path.write_bytes(audio)
            argv = [os.path.expanduser(arg).replace(AUDIO, str(path)) for arg in self.command]
            if not any(AUDIO in arg for arg in self.command):
                argv.append(str(path))
            try:
                done = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=self.timeout_s)
            except FileNotFoundError:
                raise TranscriptionError(f"{self.command[0]} not found") from None
            except subprocess.TimeoutExpired:
                raise TranscriptionError(f"the command took longer than {self.timeout_s:g}s") from None
            except OSError as error:
                raise TranscriptionError(f"{self.command[0]}: {error.strerror}") from None
        if done.returncode:
            lines = [line for line in done.stderr.splitlines() if line.strip()]
            raise TranscriptionError(lines[-1].strip() if lines else f"the command exited {done.returncode}")
        return done.stdout.strip()
