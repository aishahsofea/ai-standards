import re
from pathlib import Path

ARTIFACTS = ("issue", "analysis", "decisions", "plan")
MAX_SLUG_LENGTH = 50


def slugify(idea: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", idea.lower()).strip("-")[:MAX_SLUG_LENGTH].strip("-")
    if not slug:
        raise ValueError("idea has no usable characters for a slug")
    return slug


class RunDir:
    def __init__(self, repo: Path, slug: str) -> None:
        self.slug = slug
        self.path = repo / ".agent" / "runs" / slug
        self.path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_idea(cls, repo: Path, idea: str) -> "RunDir":
        return cls(repo, slugify(idea))

    def artifact_path(self, name: str) -> Path:
        if name in ARTIFACTS:
            return self.path / f"{name}.md"
        raise ValueError(f"unknown artifact: {name}")

    def phase_summary_path(self, phase: int) -> Path:
        if phase < 1:
            raise ValueError("phase numbers start at 1")
        return self.path / f"phase-{phase}-summary.md"

    def exists(self, path: Path) -> bool:
        return path.is_file()

    def read(self, path: Path) -> str:
        return path.read_text()

    def write(self, path: Path, text: str) -> None:
        path.write_text(text)
