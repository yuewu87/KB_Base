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


def test_write_env_updates_the_last_duplicate(tmp_path):
    """同名键出现两次时改**最后一处**。

    读的是最后一处（`dotenv` 也是后写的赢），改前一处会变成
    「保存成功但配置没变」——实测过。
    """
    p = tmp_path / ".env"
    p.write_text("KB_LLM_MODEL=first\nKB_LLM_MODEL=second\n", encoding="utf-8")

    write_env(p, {"KB_LLM_MODEL": "new"})

    assert read_env(p)["KB_LLM_MODEL"] == "new"


def test_write_env_keeps_lf_line_endings(tmp_path):
    """**写回不许把换行翻译成 CRLF。**

    `Path.write_text` 在 Windows 上默认做换行翻译——用户保存一次设置，
    他那份 LF 的 `.env` 就整份变成 CRLF，与「原样保留」矛盾。
    上一批是从一条红测的断言 diff 里看见的。
    """
    p = tmp_path / ".env"
    p.write_bytes(b"KB_LLM_MODEL=old\nKB_PORT=\n")

    write_env(p, {"KB_LLM_MODEL": "new"})

    raw = p.read_bytes()
    assert b"\r" not in raw, "写回把换行翻译成 CRLF 了"
    assert raw == b"KB_LLM_MODEL=new\nKB_PORT=\n"


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


def test_manifest_snapshot():
    """**清单是这个模块存在的理由，得钉住。**

    不然把 `default="6"` 改成 `"7"`、或从「服务」组漏掉一个键，
    测试全绿，而界面上显示的值就错了。
    """
    snapshot = [
        (g.name, [(f.key, f.kind, f.default, f.choices) for f in g.fields])
        for g in GROUPS
    ]
    assert snapshot == [
        ("模型配置", [
            ("KB_LLM_MODEL", "text", "", ()),
            ("KB_LLM_BASE_URL", "text", "", ()),
            ("KB_LLM_API_KEY", "secret", "", ()),
        ]),
        ("知识库", [
            ("KB_VAULT_PATH", "text", "", ()),
        ]),
        ("服务", [
            ("KB_PORT", "readonly", "", ()),
            ("KB_LOG_LEVEL", "choice", "INFO", ("INFO", "DEBUG")),
            ("KB_SWEEP_INTERVAL", "int", "6", ()),
            ("KB_LOG_KEEP_DAYS", "int", "90", ()),
        ]),
        ("外观", [
            ("KB_SKIN", "choice", "garnet",
             ("archive", "dark-pink", "aurora", "garnet", "neon", "mono")),
        ]),
    ]


def test_readonly_fields_are_not_editable():
    """端口改了就换地址、书签作废，仍然只读。

    **vault 路径不再只读**（2026-09-22）。当初把它设成只读是本机被改废过的
    教训，现在敢放开，靠的是两条机械约束：改路径时目标必须是个已初始化的库
    （`validate` 里那条 `_vault_path_problem`），以及「搬家」这个显式动作。
    放开的是输入框，不是判断。
    """
    keys = editable_keys()
    assert "KB_VAULT_PATH" in keys
    assert "KB_PORT" not in keys
    assert "KB_LLM_MODEL" in keys


def test_the_env_groups():
    """`.env` 里的四组。

    **「关于」不在这里**——它显示的是运行时的东西（服务状态、版本），
    不是 `.env` 里的键，由 `router.settings_context()` 拼出来。

    「外观」这一组是给皮肤的：入口虽然也在左栏底部，配置项仍然摆在这一页
    ——这里是「所有能改的配置」的清单，藏起来会让人找不到。
    """
    assert [g.name for g in GROUPS] == ["模型配置", "知识库", "服务", "外观"]


# ---------- 校验 ----------

def test_skin_is_a_choice_field():
    from kb.core.settings import find_field
    from kb.web.skins import DEFAULT_SKIN

    field = find_field("KB_SKIN")
    assert field is not None
    assert field.kind == "choice"
    # 不写死名字：这条守的是「它是下拉框、默认值是默认那套」，
    # 不是「默认永远是现有蓝」。四处默认必须一致由
    # `tests/test_config.py::test_the_default_skin_agrees_in_all_four_places` 钉。
    assert field.default == DEFAULT_SKIN


def test_skin_choices_do_not_drift_from_the_web_layer():
    """选项表与 `kb.web.skins` 是**两份**（config/settings 不该依赖 web 层）。

    漂了就是这个症状：下拉框里有一套皮肤，模板渲染出来的是另一套，
    选中任何一个都对不上。
    """
    from kb.core.settings import find_field
    from kb.web.skins import SKIN_IDS

    assert tuple(find_field("KB_SKIN").choices) == tuple(SKIN_IDS)


def test_skin_rejects_unknown_value():
    with pytest.raises(SettingsError, match="皮肤"):
        validate({"KB_SKIN": "purple"})


@pytest.mark.parametrize("skin_id", ["archive", "dark-pink", "aurora", "garnet", "neon", "mono"])
def test_skin_accepts_every_known_value(skin_id):
    assert validate({"KB_SKIN": skin_id}) == {"KB_SKIN": skin_id}


def test_skin_help_does_not_promise_a_restart():
    """它是**当场生效**的那一类（`get_cfg()` 每请求现读）——别抄成「下次启动」。"""
    from kb.core.settings import find_field

    help_text = find_field("KB_SKIN").help
    assert "立刻生效" in help_text
    assert "下次启动" not in help_text


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
    """**后端不信前端。** 只读字段与服务端不认识的键一律丢掉。

    这条原来拿 `KB_VAULT_PATH` 当「只读」的例子，2026-09-22 起它不再是只读，
    改由 `KB_NOT_A_KEY` 顶这个位置——顺带把「服务端不认识的键」那半句也验上。
    """
    out = validate({"KB_PORT": "1", "KB_NOT_A_KEY": "x", "KB_LLM_MODEL": "m"})
    assert out == {"KB_LLM_MODEL": "m"}


def test_validate_keeps_empty_api_key_out():
    """API Key 留空表示「不改」——不能把它当空串写回去。"""
    assert validate({"KB_LLM_API_KEY": ""}) == {}
    assert validate({"KB_LLM_API_KEY": "   "}) == {}


@pytest.mark.parametrize("bad", [5, 6.5, ["a"], {"b": 1}, True])
def test_validate_rejects_non_string_for_text_fields(bad):
    """POST 走 JSON——客户端送什么类型都收得到。

    **非字符串不强转**：`str(None)` 是字面量「None」，写进 `.env` 就是把
    配置写坏。文本字段拿到非字符串，一律当空处理 → 撞上「不能留空」。
    """
    with pytest.raises(SettingsError, match="模型名不能留空"):
        validate({"KB_LLM_MODEL": bad})


def test_validate_treats_json_null_as_empty():
    """JSON 的 `null` 不是字符串。文本字段当空处理（→ 报错），
    密钥当「没填」（→ 不改），**都不会把 `None` 写进 `.env`**。"""
    with pytest.raises(SettingsError, match="不能留空"):
        validate({"KB_LLM_MODEL": None})
    assert validate({"KB_LLM_API_KEY": None}) == {}


def test_validate_accepts_a_json_number_for_an_int_field():
    """int 类允许数字——表单送字符串，但手写请求送数字也该收。"""
    assert validate({"KB_SWEEP_INTERVAL": 6}) == {"KB_SWEEP_INTERVAL": "6"}


def test_validate_rejects_empty_text_fields():
    """留空会把服务写坏：模型名变成空串，之后每次调模型都失败。"""
    with pytest.raises(SettingsError, match="模型名"):
        validate({"KB_LLM_MODEL": ""})
    with pytest.raises(SettingsError, match="API 地址"):
        validate({"KB_LLM_BASE_URL": "   "})


def test_validate_reports_every_bad_field():
    """一次报全，别让人改一个跑一次。"""
    with pytest.raises(SettingsError) as exc:
        validate({"KB_LOG_LEVEL": "TRACE", "KB_SWEEP_INTERVAL": "0"})
    assert "日志级别" in str(exc.value)
    assert "巡检间隔" in str(exc.value)


def test_slow_fields_say_they_need_a_restart():
    """`KB_SWEEP_INTERVAL` / `KB_LOG_KEEP_DAYS` **只在服务启动那一刻用一次**。

    界面曾经对它们也说「立刻生效」，而实际什么都不会发生——这是对用户的
    明示承诺，且没有任何地方提示要重启。现在各自在 help 里说清楚。
    """
    from kb.core.settings import find_field

    for key in ("KB_SWEEP_INTERVAL", "KB_LOG_KEEP_DAYS"):
        assert "下次启动" in find_field(key).help


# ---------- 改路径（spec 9.2） ----------

def _vault_at(tmp_path, *, with_git: bool) -> str:
    """造一个（或不是）已初始化的库，返回它的路径字符串。"""
    path = tmp_path / "库"
    path.mkdir(exist_ok=True)           # 同一个用例里会被调两次，取路径 + 核路径
    if with_git:
        (path / ".git").mkdir(exist_ok=True)
    return str(path)


def test_vault_path_accepts_an_initialized_vault(tmp_path):
    """**这是「换机器后路径变了」那条路**——库还在，只是位置不同。"""
    clean = validate({"KB_VAULT_PATH": _vault_at(tmp_path, with_git=True)})
    assert clean["KB_VAULT_PATH"] == _vault_at(tmp_path, with_git=True)


def test_vault_path_rejects_a_plain_directory(tmp_path):
    """指到一个没有 `.git` 的目录 = 把服务换废：收件箱建起来、领域是空的、
    每条都掉进待归类。文案要告诉用户两条正路。"""
    with pytest.raises(SettingsError) as exc:
        validate({"KB_VAULT_PATH": _vault_at(tmp_path, with_git=False)})
    assert "迁移到别处" in str(exc.value)
    assert "移除知识库" in str(exc.value)


def test_vault_path_rejects_a_missing_path(tmp_path):
    with pytest.raises(SettingsError, match="还没有知识库"):
        validate({"KB_VAULT_PATH": str(tmp_path / "根本没有这个目录")})


def test_vault_path_rejects_empty(tmp_path):
    """**不给「留空 = 解绑」。**

    那会留下笔记、会话、日志在原地，而界面上显示成「还没有知识库」——
    痕迹还在、界面说没了，正是本设计要消灭的那种状态。解绑走「移除知识库」。

    **钉的是「走的哪条出口」，不是「有没有报错」。** 原来写
    `match="移除知识库"`，可路径分支的文案里也含这四个字（「想从零建先
    『移除知识库』」）——实现要是退化成「空值走路径分支」（计划原来那个 bug
    的形状），这条用例照样绿，而「三种失败各有各的出口」正是本任务的核心。
    `要解绑请用` 只在那条专用分支里出现。
    """
    with pytest.raises(SettingsError, match="要解绑请用"):
        validate({"KB_VAULT_PATH": ""})


def test_vault_path_rejects_whitespace_only(tmp_path):
    """纯空格和空串走**同一条**出口——`text` 是先 `strip()` 过的。"""
    with pytest.raises(SettingsError, match="要解绑请用"):
        validate({"KB_VAULT_PATH": "   "})


def test_vault_path_rejects_a_relative_path(tmp_path):
    """**相对路径会把库指到 KN_Base 仓库自己身上。**

    服务的 cwd 就是工程根（`spawn_service` 用 `cwd=PROJECT_ROOT`），那儿正好
    有 `.git`——只看 `(where / ".git").exists()` 的话，提交 `.` 会被判成
    「已初始化的库」，`.env` 里写下 `KB_VAULT_PATH=.`，长出的是同一个半个库。
    **这条用例必须在工程根下跑才咬得住**，而 `pytest` 的 cwd 正是那儿。
    """
    with pytest.raises(SettingsError, match="绝对路径"):
        validate({"KB_VAULT_PATH": "."})
    with pytest.raises(SettingsError, match="绝对路径"):
        validate({"KB_VAULT_PATH": "./"})


def test_missing_vault_key_is_not_an_error():
    """`.env` 里没这一行 ≠ 用户想把路径改成空。

    `validate` 只处理**提交上来的**键；设置窗没提交它，就不该报错。
    这条和上一条是一对，别把空的当成一个错误。
    """
    assert validate({"KB_LLM_MODEL": "m"}) == {"KB_LLM_MODEL": "m"}
