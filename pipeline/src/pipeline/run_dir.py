import re
import shutil
import tempfile
from pathlib import Path

STAGE_NAME = r"issue|analyze|decide|plan|implement-phase-[1-9]\d*|test|docs"
ARTIFACT_NAME = re.compile(
    rf"issue|analysis|decisions|plan|test-report|pr|cost|phase-[1-9]\d*-summary|(?:{STAGE_NAME})\.blocked"
)
MAX_SLUG_LENGTH = 50


def slugify(idea: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", idea.lower()).strip("-")[:MAX_SLUG_LENGTH].strip("-")
    if not slug:
        raise ValueError("idea has no usable characters for a slug")
    return slug


def check_artifact(name: str) -> None:
    if not ARTIFACT_NAME.fullmatch(name):
        raise ValueError(f"unknown artifact: {name}")


class RunDir:
    def __init__(self, repo: Path, slug: str) -> None:
        self.slug = slug
        self.path = repo / ".agent" / "runs" / slug
        self.path.mkdir(parents=True, exist_ok=True)
        self._staging: Path | None = None

    @classmethod
    def from_idea(cls, repo: Path, idea: str) -> "RunDir":
        return cls(repo, slugify(idea))

    @property
    def state_path(self) -> Path:
        return self.path / "state.json"

    def stage_inputs(self, texts: dict[str, str]) -> list[Path]:
        for name in texts:
            check_artifact(name)
        if self._staging is None:
            self._staging = Path(tempfile.mkdtemp(prefix="pipeline-inputs-"))
        paths = [self._staging / f"{name}.md" for name in texts]
        for path, text in zip(paths, texts.values()):
            path.write_text(text)
        return paths

    def close(self) -> None:
        if self._staging:
            shutil.rmtree(self._staging, ignore_errors=True)
            self._staging = None
