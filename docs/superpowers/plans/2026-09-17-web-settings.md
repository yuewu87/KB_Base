# 设置页与退出按钮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 侧栏加「设置」与红色「退出」——点设置开一个模态窗，当场改模型/日志级别/巡检间隔并**当场生效**；点退出停掉服务。

**Architecture:** 配置项清单收在 `kb/core/settings.py` 一处，路由与模板都读它。保存 = 校验 → 逐行改 `.env`（保留注释）→ 重载 → 让该失效的失效。热重载要把 `create_app` 里捕获死的 `cfg` 换成 `get_cfg` 回调——跟现成的 `get_llm` 一个路子。

**Tech Stack:** Python 3.11、FastAPI、Jinja2、pytest、ruff、conda 环境 `kn_base`

**设计全文：** [`docs/superpowers/specs/2026-09-17-web-settings-design.md`](../specs/2026-09-17-web-settings-design.md)

---

## 文件结构

| 文件 | 职责 | 本计划动它什么 |
|---|---|---|
| `src/kb/core/settings.py` | **新增**。配置项清单 + `.env` 的读改写 | 一个模块管「有哪些能改、怎么改」 |
| `src/kb/config.py` | 读 `.env` 造 `Config` | 加三个字段；加 `reload_config` |
| `src/kb/core/sweep_state.py` | 巡检的状态与到期判断 | `due()` 收 `interval_days` |
| `src/kb/api/http.py` | 服务编排 | `create_app` 持 `state["cfg"]`；`get_cfg`；`apply_settings`；`main()` 传保留天数 |
| `src/kb/web/router.py` | 路由 | `cfg` → `get_cfg`；新增 `/settings`（GET/POST）与 `/quit` |
| `src/kb/web/templates/_settings.html` | **新增**，模态窗内容 | |
| `src/kb/web/templates/base.html` | 页面骨架 | 侧栏两个按钮、遮罩层、脚本 |
| `src/kb/web/static/style.css` | 样式 | 模态、红色退出按钮、表单 |
| `.env.example` | 配置样板 | 补三个新键 |
| `tests/core/test_settings.py` | **新增** | `.env` 读写与校验 |
| `tests/test_config.py` | | 新字段与重载 |
| `tests/core/test_sweep_state.py` | | `due` 的可配间隔 |
| `tests/web/test_router.py` | | 三个新路由 |
| `docs/`、`README.md` | | 见 Task 7 |

**测试总数基线：465 个。**

**命令速查（本机 `conda run` 会报内部错误，勿用）：**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -v
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

---

## Task 1: `settings.py` —— 配置项清单与 `.env` 读写

**这是整件事的地基。** 有哪几项能改、怎么改，只在这一个地方定义——路由、模板、校验全读它。

**Files:**
- Create: `src/kb/core/settings.py`
- Create: `tests/core/test_settings.py`

- [ ] **Step 1: 写失败的测试**

新建 `tests/core/test_settings.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_settings.py -v
```

**Expected:** 收集期 `ModuleNotFoundError: No module named 'kb.core.settings'`

- [ ] **Step 3: 写实现**

新建 `src/kb/core/settings.py`：

```python
"""网页上能改哪些配置、`.env` 怎么读怎么写。

**配置项清单只在这里定义一处**——路由、模板、校验全读它。散开写的话，
加一项要改三处，漏一处就是「界面上有、后端不认」或者反过来。

## 两条硬规矩

**只读的字段，后端也不信前端。** vault 路径换错了整个服务当场废、端口改了
就换地址（书签作废，见 `04_踩坑与经验.md` 第 20 条）——前端不给改，
后端**也**要把它们从提交里丢掉，不能只靠界面。

**API Key 留空 = 不改。** 掩码显示的字段，用户不填就是不想动它；
当成空串写回去等于把 key 抹了。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class SettingsError(ValueError):
    """有字段填得不对。消息里逐条说清是哪个。"""


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str                       # text / secret / choice / int / readonly
    help: str = ""
    choices: tuple[str, ...] = ()
    default: str = ""


@dataclass(frozen=True)
class Group:
    name: str
    fields: tuple[Field, ...] = field(default_factory=tuple)


GROUPS: tuple[Group, ...] = (
    Group("模型配置", (
        Field("KB_LLM_MODEL", "模型名", "text",
              help="换完点「测试连接」验一下，不用重启"),
        Field("KB_LLM_BASE_URL", "API 地址", "text"),
        Field("KB_LLM_API_KEY", "API Key", "secret",
              help="掩码显示。留空表示不改"),
    )),
    Group("知识库", (
        Field("KB_VAULT_PATH", "vault 路径", "readonly",
              help="换库不是常事，换错了整个服务当场废。要改去改 .env"),
    )),
    Group("服务", (
        Field("KB_PORT", "端口", "readonly",
              help="改了地址就变，你收藏的书签就废了"),
        Field("KB_LOG_LEVEL", "日志级别", "choice",
              choices=("INFO", "DEBUG"), default="INFO",
              help="排查问题时切 DEBUG"),
        Field("KB_SWEEP_INTERVAL", "巡检间隔（天）", "int", default="6"),
        Field("KB_LOG_KEEP_DAYS", "服务侧日志保留（天）", "int", default="90"),
    )),
)

_BY_KEY = {f.key: f for g in GROUPS for f in g.fields}

# 界面上给看、但提交也不改的
_READONLY = {f.key for g in GROUPS for f in g.fields if f.kind == "readonly"}


def find_field(key: str) -> Field | None:
    return _BY_KEY.get(key)


def editable_keys() -> set[str]:
    """能改的那些键（只读与不认识的都不在里面）。"""
    return {k for k, f in _BY_KEY.items() if f.kind != "readonly"}


# ------------------------------------------------------------ .env 读写

def read_env(path: Path) -> dict[str, str]:
    """读 `.env` 成字典。文件不存在返回空字典。

    **不走 `dotenv`**——这里的用途是「原样拿回来给人看、改完再写回去」，
    要的是文件本身的样子，不是合并了环境变量之后的结果。
    """
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value.strip()
    return out


def write_env(path: Path, updates: dict[str, str]) -> None:
    """只改指定键的值，**注释、空行、顺序一律原样保留**。

    `.env` 是人手工维护的——里面有解释每一项怎么填的注释。整个文件重写
    会把注释全抹掉，那是把人写的东西弄丢了。

    文件里没有的键**追加到末尾**（第一次加新配置项时走这条）。
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)

    for key, value in remaining.items():
        out.append(f"{key}={value}")

    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ------------------------------------------------------------ 校验

def validate(raw: dict[str, str]) -> dict[str, str]:
    """把提交上来的值过一遍。返回**该写进 `.env` 的那些**。

    只读字段、不认识的键、留空的密钥——都在这里丢掉。
    有问题就抛 `SettingsError`，**一次报全**，别让人改一个跑一次。
    """
    clean: dict[str, str] = {}
    problems: list[str] = []

    for key, value in raw.items():
        spec = _BY_KEY.get(key)
        if spec is None or spec.kind == "readonly":
            continue                    # 后端不信前端：只读与服务端不认识的，丢掉

        value = (value or "").strip()

        if spec.kind == "secret" and not value:
            continue                    # 留空 = 不改
        if spec.kind == "choice" and value not in spec.choices:
            problems.append(
                f"{spec.label}只能取 {'、'.join(spec.choices)}，收到的是「{value}」"
            )
            continue
        if spec.kind == "int":
            try:
                number = int(value)
            except ValueError:
                problems.append(f"{spec.label}要填整数，收到的是「{value}」")
                continue
            if number <= 0:
                problems.append(f"{spec.label}要大于 0")
                continue
            clean[key] = str(number)
            continue

        clean[key] = value

    if problems:
        raise SettingsError("；".join(problems))
    return clean
```

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_settings.py -v
```

**Expected:** 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/kb/core/settings.py tests/core/test_settings.py
git commit -F - <<'MSG'
feat: 配置项清单与 .env 的读改写

配置项清单只定义一处——路由、模板、校验全读它。散开写的话加一项要改三处。

两条硬规矩写进代码：**只读字段后端也不信前端**（vault 路径换错了整个服务
当场废、端口改了书签作废），**API Key 留空 = 不改**（掩码字段不填就是不想
动它，当空串写回去等于把 key 抹了）。

`.env` 的写回**逐行改、保留注释与顺序**——那是人手工维护的文件，
里面写着每一项怎么填。整个重写会把注释全抹掉。
MSG
```

---

## Task 2: `Config` 加三个字段 + 重载

**Files:**
- Modify: `src/kb/config.py`
- Modify: `tests/test_config.py`
- Modify: `.env.example`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_config.py` 末尾：

```python
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
```

**注意**：该文件开头要能拿到 `load_config` / `reload_config` 与 `os`。先看现成的 import 行，缺的补上。

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/test_config.py -k "new_fields or reload" -v
```

**Expected:** 收集期就报错——`ImportError: cannot import name 'reload_config' from 'kb.config'`

- [ ] **Step 3: 改实现**

`src/kb/config.py` 整份替换：

```python
"""读取工程根目录的 .env 配置。

配置集中在一个文件夹（Q32），不散到用户目录。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

# 本文件位于 <root>/src/kb/config.py，向上三层即工程根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 运行数据的根：运行日志、service.json、会话历史、工具缓存全在它下面。
#
# **整棵被 .gitignore 排除。** 代码仓库是 public 的，而会话历史里有个人对话内容
# ——落错地方就等于公开发布。所以凡是「服务运行时产生的东西」，路径一律
# **从这里往下拼**，不要直接拿 PROJECT_ROOT 拼。
#
# 有测试守着这条（tests/test_architecture.py）。
DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_VAULT_PATH = Path(r"E:\KB_Library")


class ConfigError(RuntimeError):
    """配置缺失或非法。"""


@dataclass(frozen=True)
class Config:
    # repr=False：key 不能进日志、终端或异常上下文
    llm_api_key: str = field(repr=False)
    llm_base_url: str
    llm_model: str
    vault_path: Path
    port: int | None
    # 下面三个有默认值——老 `.env` 不改也能跑起来（它们以前是硬编码常量）
    log_level: str = "INFO"
    sweep_interval_days: int = 6
    keep_days: int = 90


def _int_or(values: Mapping, key: str, default: int) -> int:
    raw = str(values.get(key) or "").strip()
    try:
        number = int(raw)
    except ValueError:
        return default
    return number if number > 0 else default


def _build(get: Mapping) -> Config:
    """从一份键值里造 Config。缺必填项时抛 ConfigError。

    **必填项只在 `load_config` 那条路（服务启动）上严格**；`reload_config`
    走同一份代码——启动时能起来，说明必填的都在，重载时不该再因为
    某个键被删掉就整个挂掉。
    """

    def required(key: str) -> str:
        value = str(get.get(key) or "").strip()
        if not value:
            raise ConfigError(
                f"缺少必填配置 {key}。请复制 .env.example 为 .env 并填写。"
            )
        return value

    vault_raw = str(get.get("KB_VAULT_PATH") or "").strip()
    port_raw = str(get.get("KB_PORT") or "").strip()

    return Config(
        llm_api_key=required("KB_LLM_API_KEY"),
        llm_base_url=required("KB_LLM_BASE_URL"),
        llm_model=required("KB_LLM_MODEL"),
        vault_path=Path(vault_raw) if vault_raw else DEFAULT_VAULT_PATH,
        port=int(port_raw) if port_raw.isdigit() else None,
        log_level=(str(get.get("KB_LOG_LEVEL") or "").strip() or "INFO").upper(),
        sweep_interval_days=_int_or(get, "KB_SWEEP_INTERVAL", 6),
        keep_days=_int_or(get, "KB_LOG_KEEP_DAYS", 90),
    )


def load_config(env_file: Path | None = None) -> Config:
    """从 .env 读取配置（服务启动时用）。缺必填项时抛 ConfigError。

    注意：load_dotenv 会写入进程级 os.environ，所以**同一个进程内只应调用一次**。
    重复传入不同的 env_file 不会覆盖已设置的变量（override=False）。

    改了配置要重新读的话用 `reload_config`——**别拿这个函数重读**。
    """
    env_file = env_file or PROJECT_ROOT / ".env"
    load_dotenv(env_file, override=False)
    return _build(os.environ)


def reload_config(env_file: Path | None = None) -> Config:
    """重新读 .env 造一份新 Config（热重载用）。

    **用 `dotenv_values` 直接解析文件，不走 `os.environ`。** 两个理由：

    1. `load_dotenv` 是 override=False 的——已经设过的不覆盖，改了文件也读不到，
       重载会变成空转（实测：改完模型名，重载回来还是旧的）。
    2. 重载不该污染进程环境。它是「读文件造一份新的」，不是「改环境」。

    文件不存在时用默认值造一份，**不抛**——用户可能刚把 `.env` 删了。
    """
    env_file = env_file or PROJECT_ROOT / ".env"
    values = dotenv_values(env_file) if env_file.is_file() else {}
    try:
        return _build(values)
    except ConfigError:
        # 重载时必填项没了（用户手滑删了行）——别把服务带崩，
        # 沿用默认值；下一次真要用的时候自然会在调用点上报错。
        return _build({**values, "KB_LLM_API_KEY": "?", "KB_LLM_BASE_URL": "?",
                       "KB_LLM_MODEL": "?"})
```

**同时**给 `.env.example` 补三个键（追加到末尾）：

```
# 日志级别：INFO（默认）/ DEBUG（排查问题时用）
KB_LOG_LEVEL=INFO
# 距上次巡检超过这么多天就自动跑一次
KB_SWEEP_INTERVAL=6
# 服务侧日志（流程 + 运行）保留多少天，更早的启动时清掉
KB_LOG_KEEP_DAYS=90
```

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/test_config.py -v
```

**Expected:** 全 PASS（含原有的）

- [ ] **Step 5: 提交**

```bash
git add src/kb/config.py tests/test_config.py .env.example
git commit -F - <<'MSG'
feat: Config 加日志级别/巡检间隔/日志保留；加 reload_config

三个新字段都有默认值——它们以前是硬编码常量，老 `.env` 不改也能跑。

`reload_config` **用 `dotenv_values` 直接解析文件，不走 os.environ**：
`load_dotenv` 是 override=False 的，已经设过的不覆盖，改了文件也读不到，
重载会变成空转。顺带也不污染进程环境。
MSG
```

---

## Task 3: 两个常量变成配置

巡检间隔（6 天）与服务侧日志保留（90 天）现在是硬编码。「6 天是拍的」正挂在 `01_架构.md` 第十四节的待办里——这一步把它变成可调的。

**Files:**
- Modify: `src/kb/core/sweep_state.py`
- Modify: `src/kb/api/http.py`（两处调用点）
- Modify: `tests/core/test_sweep_state.py`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/core/test_sweep_state.py` 末尾：

```python
def test_due_respects_the_configured_interval(tmp_path):
    """巡检间隔现在是配置（`KB_SWEEP_INTERVAL`），不是写死的 6 天。"""
    when = datetime(2026, 9, 17, 12, 0)
    sweep_state.save_report(tmp_path, {"summary": "x"}, when=when - timedelta(days=4))

    assert sweep_state.due(tmp_path, now=when, interval_days=3) is True
    assert sweep_state.due(tmp_path, now=when, interval_days=10) is False


def test_due_falls_back_to_the_default(tmp_path):
    """不给就用默认的 6 天。"""
    when = datetime(2026, 9, 17, 12, 0)
    sweep_state.save_report(tmp_path, {"summary": "x"}, when=when - timedelta(days=4))

    assert sweep_state.due(tmp_path, now=when) is False
    assert sweep_state.due(tmp_path, now=when + timedelta(days=3)) is True
```

**注意**：该文件顶部的 import 里要有 `timedelta` 与 `datetime`，缺的补上。

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_sweep_state.py -k "configured_interval or falls_back" -v
```

**Expected:** FAIL——`TypeError: due() got an unexpected keyword argument 'interval_days'`

- [ ] **Step 3: 改实现**

`src/kb/core/sweep_state.py` 第 17-18 行与 `due()` 改成：

```python
# 距上次超过这个间隔就该跑。**默认值**——真值来自配置（`KB_SWEEP_INTERVAL`），
# 由调用方传进来。用户原话是「一次（6 天），超过才跑」，但 6 这个数是拍的。
SWEEP_INTERVAL_DAYS = 6
```

```python
def due(
    data_dir: Path,
    now: datetime | None = None,
    interval_days: int = SWEEP_INTERVAL_DAYS,
) -> bool:
    """距上次巡检是否已超过 `interval_days`。从没跑过 → True。"""
    last = load_state(data_dir).get("last_sweep")
    if not last:
        return True
    try:
        last_at = datetime.strptime(last, _FMT)
    except ValueError:
        return True
    return (now or datetime.now()) - last_at > timedelta(days=interval_days)
```

`src/kb/api/http.py` 里两处调用点改成传配置：

- `main()` 的 `if sweep_state.due(DATA_DIR):` → `if sweep_state.due(DATA_DIR, interval_days=cfg.sweep_interval_days):`
- `main()` 的清理那行 → `flow.prune(DATA_DIR, cfg.keep_days) + logging_setup.prune(LOG_DIR, cfg.keep_days)`

**同时**把那行注释里的「流程 90 天、运行 90 天」改成「天数来自配置」。

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/core/test_sweep_state.py -v
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q
```

**Expected:** 全绿

- [ ] **Step 5: 提交**

```bash
git add src/kb/core/sweep_state.py src/kb/api/http.py tests/core/test_sweep_state.py
git commit -F - <<'MSG'
feat: 巡检间隔与日志保留改成可配

两个数以前是硬编码常量。「6 天是拍的」正挂在 01_架构 第十四节的待办里，
这一步把它变成能调的（网页设置窗里改）。
MSG
```

---

## Task 4: `create_app` 接线 —— `get_cfg` 与热重载

**这一步是热重载的核心。** `cfg` 现在被捕获进闭包，改不了；换成回调。

**Files:**
- Modify: `src/kb/api/http.py`
- Modify: `src/kb/web/router.py`
- Modify: `tests/web/test_router.py`（`create_app` 调用点）

- [ ] **Step 1: 写失败的测试**

追加到 `tests/web/test_router.py` 末尾：

```python
# ---------- 配置热重载 ----------

def test_save_settings_writes_env_and_reloads(tmp_path):
    """保存 = 写 `.env` + 重载 + 让该失效的失效。

    **重载有没有生效，不靠看内部变量验**——保存完调一次 `/settings/test`，
    它的兜底值取自 `get_cfg()`，那边看到的就是重载后的配置。
    """
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=u\nKB_LLM_MODEL=old\n", encoding="utf-8"
    )
    seen: list[str] = []

    def _build(c):
        seen.append(c.llm_model)
        return FakeLLM("{}")

    app = create_app(
        Config("k", "u", "old", tmp_path, None),
        data_dir=tmp_path, build_llm_fn=_build, env_file=env,
    )
    client = TestClient(app)

    resp = client.post("/settings", json={"values": {"KB_LLM_MODEL": "new"}})

    assert resp.status_code == 200
    assert "KB_LLM_MODEL=new" in env.read_text(encoding="utf-8")

    # 表单里没填模型名 → 兜底取当前配置 → 应当是 new
    client.post("/settings/test", json={"values": {}})
    assert seen[-1] == "new"


def test_save_settings_rejects_bad_value(client):
    resp = client.post("/settings", json={"values": {"KB_LOG_LEVEL": "TRACE"}})
    assert resp.status_code == 400
    assert "日志级别" in resp.json()["detail"]


def test_save_settings_ignores_readonly(client, vault):
    """后端不信前端——只读字段提交了也不改。"""
    before = vault.parent / "x"
    resp = client.post(
        "/settings",
        json={"values": {"KB_VAULT_PATH": "E:\\别处", "KB_LLM_MODEL": "m"}},
    )
    assert resp.status_code == 200
    assert resp.json()["saved"] == {"KB_LLM_MODEL": "m"}


def test_settings_fragment_has_no_full_page(client):
    """模态是从任意页面 fetch 进来的——只要窗口那一段，不要整页骨架。"""
    body = client.get("/settings").text
    assert "<!doctype" not in body.lower()
    assert "模型配置" in body


def test_settings_has_the_about_group(client):
    """「关于」不在 `.env` 里，是拼出来的——但界面上得有这一组。

    它的内容（服务状态、版本）来自运行时，不是配置——所以它不在
    `settings.GROUPS` 里，由 `settings_context()` 补上。
    """
    body = client.get("/settings").text
    assert "关于" in body
    assert "服务状态" in body


def test_settings_never_echoes_the_api_key(client, vault, monkeypatch):
    """**API Key 不回显原文。** 只给掩码。"""
    monkeypatch.setenv("KB_LLM_API_KEY", "sk-super-secret-value")
    body = client.get("/settings").text
    assert "sk-super-secret-value" not in body
    assert "••" in body


def test_quit_calls_the_injected_function(tmp_path):
    """**退出要能注入**——不然跑一次测试就把 pytest 自己杀了。"""
    quit_calls = []
    app = create_app(
        Config("k", "u", "m", tmp_path, None),
        llm=FakeLLM("{}"),
        data_dir=tmp_path,
        quit_fn=lambda: quit_calls.append(1),
    )
    resp = TestClient(app).post("/quit")

    assert resp.status_code == 200
    assert quit_calls == [1]
```

**注意**：`create_app` 要新增 `build_llm_fn` / `quit_fn` / `env_file` 三个可选参数；`Config` 与 `FakeLLM` 若文件里没 import 就补上。

### ⚠️ 两件必须先做的事：夹具要隔离，不然测试会改你真 `.env`

**这是老坑的第二次。** 上一次是 `create_app` 不传 `data_dir`，跑测试往真实
`data/logs/` 写流程记录（实测真库涨了 678 字节）。这次同样的形状：
**`/settings` 保存会写 `.env`**——夹具不传 `env_file`，它写的就是工程根目录那个真的。

**改 `tests/web/test_router.py` 顶部的 `client` 夹具**，加一个临时 `.env`：

```python
@pytest.fixture
def client(vault, tmp_path):
    cfg = Config(
        llm_api_key="k",
        llm_base_url="http://x",
        llm_model="m",
        vault_path=vault,
        port=None,
    )
    # **env_file 必须传**：`create_app` 的默认值是工程根目录那个真 `.env`，
    # 不传的话 `/settings` 一保存就把用户的配置改了。
    env = tmp_path / ".env"
    env.write_text(
        "KB_LLM_API_KEY=k\nKB_LLM_BASE_URL=http://x\nKB_LLM_MODEL=m\n",
        encoding="utf-8",
    )
    return TestClient(
        create_app(cfg, llm=_TwoChainLLM(), data_dir=vault, env_file=env)
    )
```

**再加一条守卫用例**（跟 `data_dir` 那条一个路子——**要真会失败**）：

```python
def test_settings_save_does_not_touch_the_real_env(client):
    """跑测试不该改工程根目录那个真 `.env`。

    **必须真的走一次保存**——只 GET `/settings` 什么都不写，那种钉子是假的
    （`/flow` 那条就是这么栽的）。验证办法：临时把夹具的 `env_file=...` 去掉，
    这条必须变红。看完改回来。
    """
    from kb.config import PROJECT_ROOT

    real = PROJECT_ROOT / ".env"
    before = real.read_bytes() if real.is_file() else None

    client.post("/settings", json={"values": {"KB_LLM_MODEL": "测试不许改真文件"}})

    after = real.read_bytes() if real.is_file() else None
    assert after == before, "测试改了工程根目录的 .env——夹具忘了传 env_file"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web/test_router.py -k "settings or quit" -v
```

**Expected:** 全 FAIL——`/settings` 与 `/quit` 都是 404

- [ ] **Step 3: 改实现**

**`src/kb/api/http.py`：**

**(a)** `create_app` 签名与内部改成：

```python
def create_app(
    cfg: Config | None = None,
    llm: LLM | None = None,
    data_dir: Path | None = None,
    quit_fn: Callable[[], None] | None = None,
    env_file: Path | None = None,
    build_llm_fn: Callable[[Config], LLM] | None = None,
) -> FastAPI:
    cfg = cfg or load_config()
    data_dir = data_dir or DATA_DIR
    flow.configure(data_dir)

    # **配置要能换。** 原来是直接捕获 `cfg` 进闭包，改不了；改成装在一个
    # 可变的盒子里，各处通过 `get_cfg()` 拿——跟现成的 `get_llm` 一个路子。
    state: dict[str, Config] = {"cfg": cfg}
    cache: dict[str, LLM | None] = {"llm": llm}

    env_path = env_file or PROJECT_ROOT / ".env"
    make_llm = build_llm_fn or build_llm

    def get_cfg() -> Config:
        return state["cfg"]

    def get_llm() -> LLM:
        if cache["llm"] is None:
            cache["llm"] = make_llm(get_cfg())
        return cache["llm"]

    def apply_settings(raw: dict[str, str]) -> dict[str, str]:
        """保存 → 重载 → 让该失效的失效。返回值是**真正写下去的**那些。

        顺序不能反：**先写文件再换内存**。写失败就抛出去，内存里跟着变
        就成了两套真相。
        """
        clean = settings.validate(raw)
        if not clean:
            return {}

        settings.write_env(env_path, clean)
        state["cfg"] = reload_config(env_path)
        cache["llm"] = None                                  # 模型三件套可能变了
        logging.getLogger().setLevel(get_cfg().log_level)    # 日志级别当场生效
        return clean
```

**(b)** 传给 router 的是回调：

```python
    app.include_router(build_router(
        get_cfg, data_dir, _chat_organize_fn, get_llm,
        apply_settings, quit_fn or _default_quit, make_llm,
    ))
```

**(c)** 文件末尾加退出实现：

```python
def _default_quit() -> None:
    """停掉服务。**先答应，再退出。**

    反过来页面拿不到响应，只会显示一个连接失败。所以起一个短延迟的定时器
    去执行真正的退出，端点立刻返回。
    """
    from kb.api import runtime

    def _die() -> None:
        runtime.clear_service_info()
        os._exit(0)          # 硬退：uvicorn 的优雅关闭在这儿不值得等

    threading.Timer(0.3, _die).start()
```

**(d)** import 补：`import os`、`from collections.abc import Callable`（若没有）、`from kb.config import PROJECT_ROOT, reload_config`、`from kb.core import settings`。

**`src/kb/web/router.py`：**

**(e)** 签名改成：

```python
def build_router(
    get_cfg: Callable[[], Config],
    data_dir: Path,
    organize_fn: Callable[[str, str, str | None], str],
    get_llm: Callable[[], LLM],
    apply_settings: Callable[[dict[str, str]], dict[str, str]],
    quit_fn: Callable[[], None],
    build_llm_fn: Callable[[Config], LLM],
) -> APIRouter:
```

> `build_llm_fn` 现在就带上：Task 6 的「测试连接」要用它。**别等那时候再加**——
> 签名改两遍，中间那一步的调用点会漏。

**(f)** 文件里所有 `cfg.xxx` 改成 `get_cfg().xxx`。**`_ctx` 里那处特别容易漏**：

```python
    def _ctx(name: str, **extra) -> dict:
        return {"active": name, "vault": str(get_cfg().vault_path), **extra}
```

**(g)** 顶部加一个请求体模型：

```python
class SettingsBody(BaseModel):
    values: dict[str, str] = {}
```

（`from pydantic import BaseModel`。）

**(h)** 三个新路由（放在 `/runtime` 之前）：

```python
    @router.get("/settings", response_class=HTMLResponse)
    def settings_fragment(request: Request):
        """模态窗的内容。**只有窗口那一段**，不带整页骨架。

        模态是从任意页面 fetch 进来的，跳页会把用户的位置弄丢。
        """
        return templates.TemplateResponse(
            request, "_settings.html", _ctx("settings", **settings_context())
        )

    @router.post("/settings")
    def settings_save(body: SettingsBody):
        """保存 + 重载。**当场生效**，不用重启。

        写失败（磁盘满、没权限）会把异常抛出去 → 500，**不重载**——
        文件没写成，内存里跟着变就成了两套真相。
        """
        try:
            saved = apply_settings(body.values)
        except settings.SettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"saved": saved}

    @router.post("/quit")
    def quit_service():
        """停掉服务。实现见 `api/http.py` 的 `_default_quit`——**先答应，再退出**。"""
        quit_fn()
        return {"ok": True}
```

**(i)** 上面用到的 `settings_context()` 是个小函数，**放在 `router.py` 模块层**（不是闭包里，它不依赖任何注入）：

```python
def settings_context() -> dict:
    """给模板的：四组字段 + 它们当前的值（密钥掩码）。

    **「关于」那一组不在 `.env` 里**——它显示的是运行时的东西（服务状态、
    版本），所以在这里拼出来。这样模板仍然只是一个循环，不用为一组开特例。
    """
    values = settings.read_env(PROJECT_ROOT / ".env")

    groups = [
        {
            "name": group.name,
            "fields": [
                {
                    "key": f.key,
                    "label": f.label,
                    "kind": f.kind,
                    "help": f.help,
                    "choices": f.choices,
                    "value": _display(f, values.get(f.key, f.default)),
                }
                for f in group.fields
            ],
        }
        for group in settings.GROUPS
    ]

    groups.append({
        "name": "关于",
        "fields": [
            {
                "key": "_service", "label": "服务状态", "kind": "readonly",
                "choices": (), "value": _service_status(),
                "help": "「改了 src/ 下的代码要 kb stop」那条坑摆在这儿——"
                        "双击 web.bat 进来的人不会去查 kb status",
            },
            {
                "key": "_repo", "label": "版本 / 仓库", "kind": "readonly",
                "choices": (), "help": "",
                "value": "KN_Base · github.com/yuewu87/KB_Base",
            },
        ],
    })
    return {"groups": groups}


def _service_status() -> str:
    """一行说清服务在不在、跑的是不是旧代码。"""
    from kb.api import runtime

    port = runtime.running_port()
    if port is None:
        return "未在运行"
    if runtime.is_stale():
        return f"已连接（:{port}）· 代码比进程新，建议重启"
    return f"已连接（:{port}）"


def _display(field, value: str) -> str:
    """密钥只给掩码——**原文一个字都不进 HTML**。"""
    if field.kind != "secret" or not value:
        return value
    return "•" * 12 + value[-4:] if len(value) > 4 else "•" * 8
```

（import 补 `PROJECT_ROOT`、`from kb.core import settings`。）

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web -v
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q
```

**Expected:** 全绿

- [ ] **Step 5: 提交**

```bash
git add src/kb/api/http.py src/kb/web/router.py tests/web/test_router.py
git commit -F - <<'MSG'
feat: 配置热重载接线（get_cfg 回调 + 三个新路由）

`cfg` 原来是直接捕获进闭包的，改不了。换成 `get_cfg()` 回调——跟现成的
`get_llm` 一个路子，仓库里已经有这个注入了。

保存的顺序不能反：**先写文件再换内存**。写失败就抛出去，
内存里跟着变就成了两套真相。

`/quit` 先答应再退出——反过来页面拿不到响应，只会显示连接失败。
退出函数可注入，不然跑一次测试就把 pytest 自己杀了。

密钥只给掩码，**原文一个字都不进 HTML**。
MSG
```

---

## Task 5: 模板与样式

**Files:**
- Create: `src/kb/web/templates/_settings.html`
- Modify: `src/kb/web/templates/base.html`
- Modify: `src/kb/web/static/style.css`

- [ ] **Step 1: 写 `_settings.html`**

```jinja
{# 设置窗的内容。**只有窗口那一段**——整页骨架由 base.html 提供，
   模态是从任意页面 fetch 进来的。 #}
<div class="settings-head">
  <span>设置</span>
  <button type="button" class="x" onclick="closeSettings()" aria-label="关闭">×</button>
</div>

<div class="settings-body">
  <nav class="settings-nav">
    {% for g in groups %}
      <button type="button" class="nav-item {{ 'active' if loop.first }}"
              data-group="{{ loop.index0 }}"
              onclick="showGroup(this)">{{ g.name }}</button>
    {% endfor %}
  </nav>

  <form class="settings-panes" id="settings-form"
        onsubmit="return saveSettings(this)">
    {% for g in groups %}
      <section class="pane" data-group="{{ loop.index0 }}"
               {{ 'hidden' if not loop.first }}>
        {% for f in g.fields %}
          <div class="field">
            <label for="f-{{ f.key }}">{{ f.label }}</label>

            {% if f.kind == 'readonly' %}
              <input id="f-{{ f.key }}" value="{{ f.value }}" readonly>
            {% elif f.kind == 'secret' %}
              <input id="f-{{ f.key }}" name="{{ f.key }}" type="password"
                     value="" placeholder="{{ f.value or '未设置' }}" autocomplete="off">
            {% elif f.kind == 'choice' %}
              <select id="f-{{ f.key }}" name="{{ f.key }}">
                {% for c in f.choices %}
                  <option value="{{ c }}" {{ 'selected' if c == f.value }}>{{ c }}</option>
                {% endfor %}
              </select>
            {% else %}
              <input id="f-{{ f.key }}" name="{{ f.key }}" value="{{ f.value }}">
            {% endif %}

            {% if f.help %}<p class="hint">{{ f.help }}</p>{% endif %}
          </div>
        {% endfor %}
      </section>
    {% endfor %}

    <p class="settings-msg" id="settings-msg" hidden></p>

    <div class="settings-actions">
      <button type="button" onclick="testConnection(this)">测试连接</button>
      <button type="submit" class="primary">保存</button>
    </div>
  </form>
</div>
```

> **只读字段不给 `name`** —— 它们不会进 FormData，也就不会提交。后端还会再挡一道（Task 4），两层。
>
> **密钥字段 `value=""`** —— 掩码放在 `placeholder` 里。**原文一个字都不进 HTML**。

- [ ] **Step 2: 改 `base.html`**

**(a)** 侧栏：在「巡检」那条之后、`.side-foot` 之前插入：

```html
      <div class="side-sep"></div>

      <button type="button" class="side-btn" onclick="openSettings()">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>
        </svg>
        <span class="side-label">设置</span>
      </button>

      <div class="side-sep"></div>

      <button type="button" class="side-btn quit" onclick="quitService()">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
          <path d="M16 17l5-5-5-5M21 12H9"/>
        </svg>
        <span class="side-label">退出</span>
      </button>
```

**(b)** `</body>` 之前（页签那段脚本之后）插入遮罩层与脚本：

```html
  <div class="overlay" id="settings-overlay" hidden>
    <div class="modal" id="settings-modal"></div>
  </div>

  <div class="overlay" id="quit-notice" hidden>
    <div class="modal notice">
      <h2>服务已停</h2>
      <p>知识库服务已经关掉了。可以关掉这个标签页了。</p>
      <p class="hint">下次用的时候双击 <code>web.bat</code>，或随便跑一条 <code>kb</code> 命令，它会自己起来。</p>
      <button type="button" onclick="document.getElementById('quit-notice').hidden = true">知道了</button>
    </div>
  </div>

  <script>
    // 设置窗：fetch 片段塞进遮罩层。不从每个页面各背一份隐藏的窗口标记——
    // 那会让每页都拖着一坨用不到的 HTML。
    async function openSettings() {
      const box = document.getElementById('settings-modal');
      box.innerHTML = '<p class="muted" style="padding:20px">载入中…</p>';
      document.getElementById('settings-overlay').hidden = false;
      const r = await fetch('/settings');
      box.innerHTML = await r.text();
    }

    function closeSettings() {
      document.getElementById('settings-overlay').hidden = true;
    }

    function showGroup(btn) {
      const modal = btn.closest('.modal');
      modal.querySelectorAll('.nav-item').forEach(function (b) {
        b.classList.toggle('active', b === btn);
      });
      modal.querySelectorAll('.pane').forEach(function (p) {
        p.hidden = p.dataset.group !== btn.dataset.group;
      });
    }

    function _msg(text, ok) {
      const el = document.getElementById('settings-msg');
      el.textContent = text;
      el.classList.toggle('bad', !ok);
      el.hidden = false;
    }

    async function saveSettings(form) {
      const values = Object.fromEntries(new FormData(form));
      const r = await fetch('/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({values: values}),
      });
      const data = await r.json().catch(function () { return {}; });
      if (r.ok) {
        const n = Object.keys(data.saved || {}).length;
        _msg(n ? '已保存 ' + n + ' 项，立刻生效' : '没有要改的', true);
      } else {
        _msg(data.detail || '保存失败', false);
      }
      return false;          // 别让表单自己提交、把页面刷掉
    }

    async function testConnection(btn) {
      btn.disabled = true;
      _msg('测试中…', true);
      const r = await fetch('/settings/test', {method: 'POST'});
      const data = await r.json().catch(function () { return {}; });
      btn.disabled = false;
      _msg(r.ok && data.ok ? ('通了 · ' + data.seconds + ' 秒') : ('不通：' + (data.detail || '未知原因')), r.ok && data.ok);
    }

    async function quitService() {
      if (!confirm('停掉知识库服务？')) return;
      try { await fetch('/quit', {method: 'POST'}); } catch (e) { /* 服务可能已经没了 */ }
      closeSettings();
      document.getElementById('quit-notice').hidden = false;
    }
  </script>
```

> **`testConnection` 走 `POST /settings/test`** —— 见 Task 6。

- [ ] **Step 3: 加样式**

追加到 `style.css` 末尾：

```css
/* ---- 侧栏的分隔线与退出 ---- */
.side-sep {
  height: 1px;
  background: #3d4753;
  margin: 8px 6px;
}

.side-btn.quit { color: #ffb4b4; }
.side-btn.quit:hover { background: #8c3b3b; color: #fff; }
body.collapsed .side-btn.quit { color: #ffb4b4; }

/* ---- 模态 ---- */
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(26, 34, 51, .38);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.modal {
  background: var(--surface);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-lift);
  width: min(680px, 92vw);
  max-height: 84vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal.notice { width: min(400px, 92vw); padding: 22px 24px; gap: 8px; }
.modal.notice h2 { margin: 0 0 4px; font-size: 17px; }

.settings-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 18px;
  border-bottom: 1px solid var(--line);
  font-weight: 600;
}

.settings-head .x {
  border: none;
  background: none;
  font-size: 20px;
  line-height: 1;
  color: var(--faint);
  cursor: pointer;
}

.settings-body { display: flex; min-height: 0; flex: 1; }

.settings-nav {
  flex: 0 0 138px;
  border-right: 1px solid var(--line);
  padding: 10px 8px;
  background: var(--paper);
}

.settings-nav .nav-item {
  display: block;
  width: 100%;
  text-align: left;
  border: none;
  background: none;
  padding: 8px 11px;
  border-radius: var(--r-sm);
  color: var(--muted);
  font: inherit;
  cursor: pointer;
  margin-bottom: 2px;
}

.settings-nav .nav-item.active {
  background: var(--blue-soft);
  color: var(--blue);
  font-weight: 600;
}

.settings-panes { flex: 1; padding: 16px 20px; overflow-y: auto; }

.settings-panes .field { margin-bottom: 13px; }
.settings-panes label { display: block; margin-bottom: 4px; color: var(--muted); }

.settings-panes input,
.settings-panes select {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  font: inherit;
  background: var(--surface);
}

.settings-panes input[readonly] {
  background: var(--line-soft);
  color: var(--faint);
}

.settings-panes .hint { margin: 4px 0 0; color: var(--faint); font-size: 11.5px; }

.settings-msg { margin: 12px 0 0; color: var(--blue); }
.settings-msg.bad { color: #a33; }

.settings-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
```

- [ ] **Step 4: 起服务肉眼过一遍**

```bash
./kb.bat stop && ./kb.bat status
PYTHONIOENCODING=utf-8 ./kb.bat web
```

**看到这些才算过**（把实际看到的写进报告）：

1. 侧栏「巡检」下面**两条分隔线**，中间夹着「设置」，最下面是**红色「退出」**
2. 点「设置」→ 遮罩 + 小窗；左列四项（模型配置 / 知识库 / 服务 / 关于），点哪项换哪项的内容
3. **模型配置**里 API Key 是掩码、输入框是空的、placeholder 里是掩码
4. **知识库**与**服务**里，vault 路径和端口是**灰底只读**
5. 改日志级别成 DEBUG → 保存 → 提示「已保存 1 项，立刻生效」，**页面没刷新**
6. 点「退出」→ 确认 → 提示窗「服务已停」；`./kb.bat status` 说服务没在跑

- [ ] **Step 5: 提交**

```bash
git add src/kb/web/templates/_settings.html src/kb/web/templates/base.html src/kb/web/static/style.css
git commit -F - <<'MSG'
feat: 设置模态窗与侧栏两个按钮

模态内容是从任意页面 fetch 进来的片段——不从每个页面各背一份隐藏的窗口标记，
那会让每页都拖着一坨用不到的 HTML。

只读字段**不给 `name`**，不进 FormData；后端还会再挡一道（两层）。
密钥字段 `value=""`、掩码放 placeholder——**原文一个字都不进 HTML**。
MSG
```

---

## Task 6: 测试连接

**Files:**
- Modify: `src/kb/web/router.py`
- Modify: `tests/web/test_router.py`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/web/test_router.py`：

```python
def test_test_connection_uses_form_values_not_saved_ones(tmp_path, monkeypatch):
    """**验的是表单里的值，不是已保存的。**

    所以「先测试再保存」这条顺序走得通——不用为了测一次就把坏配置先写进 .env。
    """
    cfg = Config("k", "u", "saved-model", tmp_path, None)
    seen: list[str] = []

    def _build(c):
        seen.append(c.llm_model)
        return FakeLLM("ok")

    app = create_app(cfg, data_dir=tmp_path, build_llm_fn=_build)
    resp = TestClient(app).post("/settings/test", json={"values": {"KB_LLM_MODEL": "typed-model"}})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert seen == ["typed-model"]


def test_test_connection_reports_failure(tmp_path):
    """连不上要报原因，别只说「失败」。"""
    class _Boom:
        def complete(self, system, user):
            raise LLMError("连不上")

    app = create_app(
        Config("k", "u", "m", tmp_path, None),
        data_dir=tmp_path,
        build_llm_fn=lambda _c: _Boom(),
    )
    resp = TestClient(app).post("/settings/test", json={"values": {}})

    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "连不上" in resp.json()["detail"]
```

**注意**：`LLMError` 从 `kb.llm.base` 来，文件里没有就补 import。

- [ ] **Step 2: 跑测试确认失败**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web/test_router.py -k "test_connection" -v
```

**Expected:** FAIL——`/settings/test` 是 404

- [ ] **Step 3: 改实现**

`src/kb/web/router.py` 加：

```python
    @router.post("/settings/test")
    def settings_test(body: SettingsBody):
        """拿**表单里当前填的值**新建一个客户端发一次最小请求。

        **不落盘、不动现有的客户端**——所以「先测试再保存」走得通，
        不用为了测一次就把坏配置先写进 `.env`。

        **它要花钱**（一次极小的调用）。这是刻意的：换模型/换 key 时，
        这是唯一能立刻知道对不对的办法。
        """
        cfg = get_cfg()
        # 表单里的值优先；没填的（比如密钥留空）沿用当前的
        merged = {
            "KB_LLM_MODEL": body.values.get("KB_LLM_MODEL") or cfg.llm_model,
            "KB_LLM_BASE_URL": body.values.get("KB_LLM_BASE_URL") or cfg.llm_base_url,
            "KB_LLM_API_KEY": body.values.get("KB_LLM_API_KEY") or cfg.llm_api_key,
        }
        probe = build_llm_fn(Config(
            llm_api_key=merged["KB_LLM_API_KEY"],
            llm_base_url=merged["KB_LLM_BASE_URL"],
            llm_model=merged["KB_LLM_MODEL"],
            vault_path=cfg.vault_path,
            port=cfg.port,
        ))

        started = time.monotonic()
        try:
            probe.complete("你是连通性测试。", "回复 ok 两个字就行。")
        except LLMError as exc:
            return {"ok": False, "detail": str(exc)}
        return {"ok": True, "seconds": round(time.monotonic() - started, 1)}
```

import 补：`import time`、`from kb.llm.base import LLMError`、`from kb.api.http import build_llm`（或把 `build_llm_fn` 也注入进来——**用注入的那个**，见下）。

`build_llm_fn` 已经在 Task 4 的 `build_router` 签名里了——直接用。

- [ ] **Step 4: 跑测试确认通过**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest tests/web -v
```

**Expected:** 全绿

- [ ] **Step 5: 提交**

```bash
git add src/kb/web/router.py src/kb/api/http.py tests/web/test_router.py
git commit -F - <<'MSG'
feat: 设置窗的「测试连接」

拿**表单里当前填的值**新建一个客户端发一次最小请求——不落盘、不动现有的
客户端，所以「先测试再保存」走得通，不用为了测一次就把坏配置先写进 .env。

它要花钱（一次极小的调用）。这是刻意的：换模型/换 key 时，
这是唯一能立刻知道对不对的办法。
MSG
```

---

## Task 7: 文档同步与端到端

**Files:**
- Modify: `docs/01_架构.md`、`docs/02_需求.md`、`docs/04_踩坑与经验.md`、`README.md`

- [ ] **Step 1: 改 `01_架构.md` 第十一节**

接口表下面补：

```markdown
**设置（2026-09-17）：** `GET /settings` 返回模态窗的片段、`POST /settings` 保存并
**当场重载**、`POST /settings/test` 拿表单里的值试连一次、`POST /quit` 停服务。

**保存即生效**——模型三件套重建客户端、日志级别当场调、巡检间隔与日志保留
每次用到时现读。**只有端口要重启**（它就是地址本身）。
```

- [ ] **Step 2: 改 `01_架构.md` 第十四节**

「定了做法但细节没定」里的第 3 条「巡检间隔的「6 天」是拍的」改成已解决：

```markdown
| 3 | ~~巡检间隔的「6 天」是拍的~~ | **已解决**：搬进网页设置窗，可调（`KB_SWEEP_INTERVAL`） |
```

- [ ] **Step 3: 改 `02_需求.md` 第五节**

Web UI 布局设想的补充一节里加：

```markdown
### 2026-09-17 补充：设置与退出

- **侧栏加两项**：「设置」（开模态窗）在最下面一组，「退出」（红底）单独在最底，
  两者之间一条分隔线——一个是功能，一个是关机
- **退出 = 停服务 → 弹提示窗**。标签页关不掉（浏览器只让 JS 关自己开的窗口），
  所以只给提示
```

- [ ] **Step 4: 改 `04_踩坑与经验.md`**

在「五、运维与配置」末尾加第 26 条：

```markdown
### 26. 配置热重载不能用 `load_dotenv` 重读

**踩到的**：设置页保存后要重载配置，第一版想当然地又调了一次 `load_dotenv`——
**改了文件也读不到新值**。

**根因**：`load_dotenv` 默认 `override=False`——**已经设过的环境变量它不覆盖**。
第一次加载把值写进了 `os.environ`，第二次就什么也不做，重载成了空转。

**修法**：用 `dotenv_values(env_file)`——直接解析文件、**返回 dict、不碰
`os.environ`**。顺带还避免了重载污染进程环境。

**教训**：「读配置」和「重新读配置」不是同一个动作。库函数的默认行为
是按「只读一次」设计的，第二次调它得先问一句「它会不会真的再读一遍」。
```

- [ ] **Step 5: 改 `README.md`**

「怎么用」那节补一句：

```markdown
侧栏最下面有 **设置**（改模型、日志级别、巡检间隔，**保存即生效**）和 **退出**
（停服务）。
```

- [ ] **Step 6: 端到端验证**

```bash
./kb.bat stop
./kb.bat status          # 服务未在运行
./kb.bat web             # 拉起来 + 开浏览器
```

逐项确认（**把实际看到的写进报告**）：

1. 侧栏两条分隔线、设置、红色退出都在
2. 设置窗能开、四组能切、只读字段是灰底
3. 改**日志级别 → DEBUG** 保存 → 提示「已保存 1 项」→ `data/logs/kb/今天的.log` 里
   之后的行应当变多（DEBUG 才有）
4. 点「测试连接」→ 报「通了 · N 秒」
5. 改回 INFO 保存
6. 点「退出」→ 确认 → 提示窗；`./kb.bat status` 说服务没在跑；
   `data/runtime/` 目录是空的

- [ ] **Step 7: 跑全套**

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

**Expected:** 全绿、`All checks passed!`

- [ ] **Step 8: 提交**

```bash
git add docs/ README.md
git commit -F - <<'MSG'
docs: 设置页与退出按钮同步

01_架构 第十一节补三个新路由与「保存即生效」的边界；第十四节把
「巡检间隔 6 天是拍的」划掉（已搬进设置窗可调）；02_需求 补侧栏两项；
04_踩坑 补第 26 条——**配置热重载不能用 load_dotenv 重读**。
MSG
```

---

## Self-Review

**1. 规格覆盖：** 设计文档十二节逐条对得上——
侧栏两按钮（Task 5）、模态双栏（Task 5）、四组（Task 1 定义 + Task 5 渲染）、
保存即生效（Task 2 的 reload + Task 4 的 apply_settings）、退出（Task 4 的
`_default_quit` + Task 5 的提示窗）、`.env` 保留注释（Task 1）、
只读不入库（Task 1 校验 + Task 4 后端 + Task 5 不给 name）、
密钥掩码（Task 4 的 `_display` + Task 5 的 `value=""`）、
两个常量变配（Task 3）、文档同步（Task 7）。

**2. 占位符扫描：** 无 TBD / TODO / 「类似 Task N」。

**3. 类型一致性：**
- `settings.validate(raw: dict[str,str]) -> dict[str,str]`，抛 `SettingsError`
- `settings.write_env(path, updates)` / `read_env(path) -> dict`
- `settings.GROUPS` / `find_field` / `editable_keys`
- `config.reload_config(env_file=None) -> Config`
- `sweep_state.due(data_dir, now=None, interval_days=SWEEP_INTERVAL_DAYS)`
- `create_app(cfg, llm, data_dir, quit_fn, env_file, build_llm_fn)`
- `build_router(get_cfg, data_dir, organize_fn, get_llm, apply_settings, quit_fn, build_llm_fn)`
- 模板上下文：`groups` → 每项 `{name, fields}`，字段 `{key,label,kind,help,choices,value}`。
  **四组**：`.env` 的三组来自 `settings.GROUPS`，「关于」由 `settings_context()` 补上
  （它的内容来自运行时，不是配置）

**4. 一处刻意的顺序：** Task 3 在 Task 4 之前——`main()` 里那两处调用点要传
`cfg.sweep_interval_days` / `cfg.keep_days`，而那两个字段是 Task 2 加的。
Task 2 → Task 3 → Task 4 的顺序不能换。

**5. 已知会碰到的：** Task 4 把 `router.py` 里所有 `cfg.xxx` 换成 `get_cfg().xxx`，
`_ctx` 那处最容易漏（它被每个端点调用）。改完跑 `tests/web` 就会暴露。

**6. 测试隔离（老坑第二次）：** `create_app` 的 `env_file` 默认是**工程根目录那个真 `.env`**。
夹具不传就会在跑测试时改用户的配置——跟上次 `data_dir` 那条一个形状
（那次实测真库涨了 678 字节）。Task 4 Step 1 里有夹具改法与守卫用例，
**守卫用例要实测能变红**，别只看它绿着就算数。

---

## 收尾

```bash
"D:/Conda_base/envs/kn_base/python.exe" -m pytest -q
"D:/Conda_base/envs/kn_base/python.exe" -m ruff check src tests scripts
```

全绿即本计划完成。
