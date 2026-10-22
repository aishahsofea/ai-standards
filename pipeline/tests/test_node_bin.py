import pytest

from pipeline.node_bin import NodeNotFound, resolve_node_bin


@pytest.fixture(autouse=True)
def no_override(monkeypatch):
    monkeypatch.delenv("PIPELINE_NODE_BIN", raising=False)


@pytest.fixture
def nvm(tmp_path):
    root = tmp_path / "nvm"
    for version in ("v22.2.0", "v22.15.0", "v20.16.0"):
        (root / version).mkdir(parents=True)
    return root


def test_override_wins(tmp_path, nvm, monkeypatch):
    monkeypatch.setenv("PIPELINE_NODE_BIN", "/custom/bin")
    assert str(resolve_node_bin(tmp_path, nvm)) == "/custom/bin"


def test_picks_newest_matching_major_from_nested_nvmrc(tmp_path, nvm):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / ".nvmrc").write_text("22\n")
    assert resolve_node_bin(tmp_path, nvm) == nvm / "v22.15.0" / "bin"


def test_no_nvmrc_leaves_path_alone(tmp_path, nvm):
    assert resolve_node_bin(tmp_path, nvm) is None


def test_missing_version_fails_fast(tmp_path, nvm):
    (tmp_path / ".nvmrc").write_text("v18")
    with pytest.raises(NodeNotFound, match="Node 18"):
        resolve_node_bin(tmp_path, nvm)
