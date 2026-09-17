"""网页上能改哪些配置、`.env` 怎么读怎么写。"""

import pytest

from kb.core.settings import (
    GROUPS,
    SettingsError,
    editable_keys,
    read_env,
    validate,
    write_env,
)

# 一份像真的 `.env`：有注释、有空行、有顺序
SAMPLE = """\
# 复制本文件为 .env 并填写。.env 不入库。
KB_LLM_API_KEY=sk-old
KB_LLM_BASE_URL=https://api.deepseek.com
# 留空则用默认值
KB_VAULT_PATH=E:\\KB_Library
KB_PORT=
"""


def test_write_env_keeps_comments_and_order(tmp_path):
    """**只换命中的那一行的值**，注释、空行、顺序一字不动。

    `.env` 是人手工维护的——里面有解释每一项怎么填的注释。
    整个文件重写会把注释全抹掉。
    """
    p = tmp_path / ".env"
    p.write_text(SAMPLE, encoding="utf-8")

    write_env(p, {"KB_LLM_MODEL": "deepseek-flash"})

    after = p.read_text(encoding="utf-8").splitlines()
    assert after[0] == "# 复制本文件为 .env 并填写。.env 不入库。"
    assert after[1] == "KB_LLM_API_KEY=sk-old"
    assert after[2] == "KB_LLM_BASE_URL=https://api.deepseek.com"
    assert after[3] == "# 留空则用默认值"
    # 原有的键都没动，新的追加在末尾
    assert after[-1] == "KB_LLM_MODEL=deepseek-flash"


def test_write_env_replaces_in_place(tmp_path):
    p = tmp_path / ".env"
    p.write_text(SAMPLE, encoding="utf-8")

    write_env(p, {"KB_LLM_BASE_URL": "https://x.test", "KB_PORT": "51823"})

    text = p.read_text(encoding="utf-8")
    assert "KB_LLM_BASE_URL=https://x.test" in text
    assert "KB_PORT=51823" in text
    assert text.count("KB_LLM_BASE_URL=") == 1      # 没有重复一行


def test_write_env_creates_missing_file(tmp_path):
    """`.env` 不存在就建一个——第一次用的人不该卡在这儿。"""
    p = tmp_path / ".env"
    write_env(p, {"KB_LLM_MODEL": "m"})
    assert read_env(p) == {"KB_LLM_MODEL": "m"}


def test_write_env_ignores_commented_out_keys(tmp_path):
    """注释掉的行不是配置，别去改它。"""
    p = tmp_path / ".env"
    p.write_text("# KB_LLM_MODEL=old\nKB_LLM_MODEL=new\n", encoding="utf-8")

    write_env(p, {"KB_LLM_MODEL": "brand-new"})

    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# KB_LLM_MODEL=old"
    assert lines[1] == "KB_LLM_MODEL=brand-new"


def test_read_env(tmp_path):
    p = tmp_path / ".env"
    p.write_text(SAMPLE, encoding="utf-8")
    values = read_env(p)
    assert values["KB_LLM_BASE_URL"] == "https://api.deepseek.com"
    assert values["KB_LLM_API_KEY"] == "sk-old"


# ---------- 清单 ----------

def test_secret_fields_are_marked():
    """API Key 要能认出来——界面上得掩码，日志里不能印。"""
    from kb.core.settings import find_field

    assert find_field("KB_LLM_API_KEY").kind == "secret"
    assert find_field("KB_LLM_MODEL").kind == "text"


def test_readonly_fields_are_not_editable():
    """vault 路径换错了整个服务当场废；端口改了就换地址、书签作废。"""
    keys = editable_keys()
    assert "KB_VAULT_PATH" not in keys
    assert "KB_PORT" not in keys
    assert "KB_LLM_MODEL" in keys


def test_the_three_env_groups():
    """`.env` 里的三组。

    **「关于」不在这里**——它显示的是运行时的东西（服务状态、版本），
    不是 `.env` 里的键，由 `router.settings_context()` 拼出来。
    """
    assert [g.name for g in GROUPS] == ["模型配置", "知识库", "服务"]


# ---------- 校验 ----------

def test_validate_rejects_bad_log_level():
    with pytest.raises(SettingsError, match="日志级别"):
        validate({"KB_LOG_LEVEL": "TRACE"})


def test_validate_accepts_debug():
    assert validate({"KB_LOG_LEVEL": "DEBUG"}) == {"KB_LOG_LEVEL": "DEBUG"}


@pytest.mark.parametrize("bad", ["0", "-1", "abc", ""])
def test_validate_rejects_bad_sweep_interval(bad):
    with pytest.raises(SettingsError, match="巡检间隔"):
        validate({"KB_SWEEP_INTERVAL": bad})


def test_validate_rejects_bad_keep_days():
    with pytest.raises(SettingsError, match="保留"):
        validate({"KB_LOG_KEEP_DAYS": "-5"})


def test_validate_drops_readonly_and_unknown():
    """**后端不信前端。** 只读字段与服务端不认识的键一律丢掉。"""
    out = validate({"KB_VAULT_PATH": "E:\\别处", "KB_PORT": "1", "KB_LLM_MODEL": "m"})
    assert out == {"KB_LLM_MODEL": "m"}


def test_validate_keeps_empty_api_key_out():
    """API Key 留空表示「不改」——不能把它当空串写回去。"""
    assert validate({"KB_LLM_API_KEY": ""}) == {}
    assert validate({"KB_LLM_API_KEY": "   "}) == {}


def test_validate_reports_every_bad_field():
    """一次报全，别让人改一个跑一次。"""
    with pytest.raises(SettingsError) as exc:
        validate({"KB_LOG_LEVEL": "TRACE", "KB_SWEEP_INTERVAL": "0"})
    assert "日志级别" in str(exc.value)
    assert "巡检间隔" in str(exc.value)
