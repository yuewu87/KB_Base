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


def test_default_env_file_is_project_root(monkeypatch, tmp_path):
    """不传 env_file 时应读工程根目录的 .env（而不是 src/.env 之类）。"""
    from kb import config

    # 下面 monkeypatch 之后，真实 PROJECT_ROOT 的正确性就不再被检验，
    # 所以先单独钉死一次：parents 索引写错一层时只有这行会红。
    assert (config.PROJECT_ROOT / "src" / "kb" / "config.py").is_file()

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    _write_env(tmp_path, VALID)
    assert load_config().llm_api_key == "k"


def test_os_env_wins_over_env_file(monkeypatch, tmp_path):
    """override=False 的语义：已存在的环境变量优先于 .env 文件。"""
    monkeypatch.setenv("KB_LLM_API_KEY", "from-os")
    assert load_config(_write_env(tmp_path, VALID)).llm_api_key == "from-os"
