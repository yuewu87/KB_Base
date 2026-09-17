import os
from pathlib import Path

import pytest

from kb.config import ConfigError, load_config, reload_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个测试前清掉配置环境变量，避免测试间相互污染。"""
    for key in (
        "KB_LLM_API_KEY",
        "KB_LLM_BASE_URL",
        "KB_LLM_MODEL",
        "KB_VAULT_PATH",
        "KB_PORT",
        "KB_LOG_LEVEL",
        "KB_SWEEP_INTERVAL",
        "KB_LOG_KEEP_DAYS",
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


# ---------- 新字段与热重载 ----------

def test_new_fields_have_defaults(tmp_path):
    """三个新字段可有可无——老 `.env` 不改也能跑起来。"""
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=m\n", encoding="utf-8"
    )
    cfg = load_config(env)
    assert cfg.log_level == "INFO"
    assert cfg.sweep_interval_days == 6
    assert cfg.keep_days == 90


def test_new_fields_are_read(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=m\n"
        "KB_LOG_LEVEL=DEBUG\nKB_SWEEP_INTERVAL=3\nKB_LOG_KEEP_DAYS=30\n",
        encoding="utf-8",
    )
    cfg = load_config(env)
    assert cfg.log_level == "DEBUG"
    assert cfg.sweep_interval_days == 3
    assert cfg.keep_days == 30


def test_bad_log_level_in_env_falls_back_to_info(tmp_path):
    """手改 .env 写成别的级别，不该让 setLevel 抛。"""
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=m\nKB_LOG_LEVEL=TRACE\n",
        encoding="utf-8",
    )
    assert load_config(env).log_level == "INFO"


def test_reload_config_sees_the_new_value(tmp_path):
    """**这条是热重载的地基。**

    不能拿 `load_dotenv` 重读——它是 override=False 的，已经设过的环境变量
    它不覆盖，改了文件也读不到，重载会变成空转。
    """
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=old\n", encoding="utf-8"
    )
    assert load_config(env).llm_model == "old"

    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=new\n", encoding="utf-8"
    )

    assert reload_config(env).llm_model == "new"


def test_reload_does_not_touch_os_environ(tmp_path, monkeypatch):
    """重载**不污染进程环境**——它是「读文件造一份新的」，不是「改环境」。

    用 `dotenv_values` 而不是 `load_dotenv`，正是为这个。
    """
    monkeypatch.delenv("KB_LLM_MODEL", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=x\n", encoding="utf-8"
    )

    reload_config(env)

    assert "KB_LLM_MODEL" not in os.environ


def test_reload_missing_file_gives_defaults(tmp_path):
    """文件不在——用默认值造一份，别抛。"""
    cfg = reload_config(tmp_path / "没有这个文件")
    assert cfg.llm_model == ""
    assert cfg.log_level == "INFO"
