import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

PIPELINE_COMMAND = (sys.executable, "-c", "import sys; from pipeline.cli import main; sys.exit(main())")


@dataclass(frozen=True)
class Config:
    repos: dict[str, Path]
    max_concurrent: int = 2
    daily_cap_usd: float = 30.0
    pipeline_command: tuple[str, ...] = PIPELINE_COMMAND
    telegram_owner_id: int | None = None
    transcribe_command: tuple[str, ...] = ()


def home() -> Path:
    return Path(os.environ.get("CONCIERGE_HOME", Path.home() / ".concierge"))


def load_config(path: Path) -> Config:
    data = json.loads(path.read_text())
    options = {key: data[key] for key in ("max_concurrent", "daily_cap_usd", "telegram_owner_id") if key in data}
    return Config(
        {name: Path(repo).expanduser() for name, repo in data["repos"].items()}, **options, transcribe_command=tuple(data.get("transcribe_command", ())),
    )
