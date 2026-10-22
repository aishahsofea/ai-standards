import os
from pathlib import Path

NVM_NODE_DIR = Path.home() / ".nvm" / "versions" / "node"


class NodeNotFound(Exception):
    pass


def resolve_node_bin(repo: Path, nvm_node_dir: Path = NVM_NODE_DIR) -> Path | None:
    if override := os.environ.get("PIPELINE_NODE_BIN"):
        return Path(override)
    nvmrc = next(iter([*repo.glob(".nvmrc"), *repo.glob("*/.nvmrc")]), None)
    if nvmrc is None:
        return None
    major = nvmrc.read_text().strip().removeprefix("v").split(".")[0]
    installed = [d for d in nvm_node_dir.glob(f"v{major}.*") if d.is_dir()]
    if not installed:
        raise NodeNotFound(f"{nvmrc} wants Node {major}, but none is installed under {nvm_node_dir}")
    return max(installed, key=lambda d: tuple(map(int, d.name.removeprefix("v").split(".")))) / "bin"
