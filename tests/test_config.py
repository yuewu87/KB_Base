from pathlib import Path

import pytest

from kb.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个测试前清掉配置环境变量，避免测试间相互污染。"""
    for key in (
        "KB_LLM_API_KEY",
        "KB_LLM_BASE_URL",
        "KB_LLM_MODEL",
        "KB_VAULT_PATH",
        "KB_PORT",
    ):
        monkeypatch.delenv(key, raising=False)


def _write_env(tmp_path: Path, content: str) -> Path:
    env = tmp_path / ".env"
    env.write_text(content, encoding="utf-8")
    return env


VALID = "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=https://x/v1\nKB_LLM_MODEL=m\n"


def test_reads_required_values(tmp_path):
    cfg = load_config(_write_env(tmp_path, VALID))
    assert cfg.llm_api_key == "k"
    assert cfg.llm_base_url == "https://x/v1"
    assert cfg.llm_model == "m"


def test_missing_required_raises_with_key_name(tmp_path):
    env = _write_env(tmp_path, "KB_LLM_BASE_URL=https://x/v1\nKB_LLM_MODEL=m\n")
    with pytest.raises(ConfigError, match="KB_LLM_API_KEY"):
        load_config(env)


def test_vault_path_defaults_when_absent(tmp_path):
    cfg = load_config(_write_env(tmp_path, VALID))
    assert cfg.vault_path == Path(r"E:\KB_Library")


def test_port_parsed_and_optional(tmp_path):
    cfg = load_config(_write_env(tmp_path, VALID))
    assert cfg.port is None

    cfg2 = load_config(_write_env(tmp_path, VALID + "KB_PORT=5200\n"))
    assert cfg2.port == 5200


def test_vault_path_override(tmp_path):
    cfg = load_config(_write_env(tmp_path, VALID + "KB_VAULT_PATH=D:\\Other\n"))
    assert cfg.vault_path == Path("D:\\Other")
