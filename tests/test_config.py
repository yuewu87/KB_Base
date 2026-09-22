import os
from pathlib import Path

import pytest

from kb.config import (
    NO_VAULT_MESSAGE,
    Config,
    ConfigError,
    load_config,
    reload_config,
    require_vault,
)


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
        "KB_SKIN",
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


def test_vault_path_is_none_when_absent(tmp_path):
    """**空值表示「没有」，不表示「回落到作者本机那个」。**

    这条是防雷测试。原先这里回落 `E:\\KB_Library`——别人的服务会安安静静地
    写进作者的库，而且看起来一切正常。
    """
    cfg = load_config(_write_env(tmp_path, VALID))
    assert cfg.vault_path is None


def test_no_hardcoded_vault_path_constant():
    """连名字都不许留——留着就会被下一个人接回去。"""
    import kb.config as config

    assert not hasattr(config, "DEFAULT_VAULT_PATH")


def test_require_vault_message_spells_out_both_steps():
    """没库时那句文案**必须说全两步**。

    `scripts/init_vault.py` 只建目录，**它不写 `.env`**（写配置一直是服务的活）。
    只说「跑这个脚本」会把人引到一个半截状态：库建好了、服务还是不知道该看哪儿。
    """
    with pytest.raises(ConfigError, match="初始化知识库"):
        require_vault(Config("k", "u", "m", None, None))
    assert "scripts/init_vault.py" in NO_VAULT_MESSAGE


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


# ---------- 皮肤 ----------

def test_skin_defaults_to_the_default_skin(tmp_path):
    """**别把默认皮肤的名字抄进这条测试。**

    写死 `"archive"` 的话，改默认值那天这条会红——而它想守的是「`.env` 里
    没这一行时用默认那套」，不是「默认永远是现有蓝」。名字直接从
    `skins.DEFAULT_SKIN` 拿。
    """
    from kb.web.skins import DEFAULT_SKIN

    assert load_config(_write_env(tmp_path, VALID)).skin == DEFAULT_SKIN


@pytest.mark.parametrize("skin", ["archive", "dark-pink", "aurora", "garnet", "neon", "mono"])
def test_skin_is_read(tmp_path, skin):
    """六套都读得出来，且**大小写不敏感**（和 `_log_level` 一致）。

    一条测试只 `load_config` 一次：`load_dotenv` 是 override=False 的，
    同一个测试里换一份 `.env` 再读，读到的还是上一次的值。
    """
    env = _write_env(tmp_path, VALID + f"KB_SKIN={skin.upper()}\n")
    assert load_config(env).skin == skin


@pytest.mark.parametrize("bad", ["purple", "  ", "dark_pink", "炭黑"])
def test_bad_skin_in_env_falls_back_to_the_default(tmp_path, bad):
    """手改 `.env` 写错皮肤名不能让服务崩。

    回落默认值跑着，设置窗里显示的就是默认值——人一看就知道不对。
    和 `_log_level` 是同一条理由：抛出去就是「文件改了、内存没换、
    客户端拿 500」的怪状态。
    """
    from kb.web.skins import DEFAULT_SKIN

    env = _write_env(tmp_path, VALID + f"KB_SKIN={bad}\n")
    assert load_config(env).skin == DEFAULT_SKIN


def test_the_copied_skin_list_does_not_drift():
    """`_VALID_SKINS` 是**故意抄的一份**（config 不该依赖 web 层）——抄漏了要有人喊。

    漂了就两头不对：`config._skin()` 会把一套合法皮肤判成非法、静默回落，
    而界面上一切正常，只是「选哪套都变回现有蓝」。
    """
    from kb.config import _VALID_SKINS
    from kb.web.skins import SKIN_IDS

    assert set(_VALID_SKINS) == set(SKIN_IDS)


def test_the_default_skin_agrees_in_all_four_places():
    """**默认皮肤这一个名字散在四处**，改的时候必须一起改。

    四处：`skins.DEFAULT_SKIN`、`config.Config.skin` 的字段默认、
    `config._skin()` 的回落、`settings` 里那个字段的 `default`。
    `config` **故意不 import `skins`**（不反过来依赖 web 层），所以拼不到一起。

    散着写的代价就是「改了三处忘了一处」，而症状很难往这上面想：
    - `_skin()` 忘了改 → 手改 `.env` 写错一个字母，回落到的不是文档说的那套
    - `settings` 忘了改 → `.env` 里没写 `KB_SKIN` 的人，设置窗显示的是旧默认，
      一保存**就把旧的那套写进 `.env`**，从此钉死
    - `skins.DEFAULT_SKIN` 忘了改 → 那一套的变量不会进 `:root`，首屏闪一下
    """
    from kb.config import _skin
    from kb.core import settings
    from kb.web.skins import DEFAULT_SKIN

    assert settings.find_field("KB_SKIN").default == DEFAULT_SKIN
    assert _skin({}) == DEFAULT_SKIN
    assert _skin({"KB_SKIN": "这套不存在"}) == DEFAULT_SKIN
    assert Config("k", "u", "m", None, None).skin == DEFAULT_SKIN


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
