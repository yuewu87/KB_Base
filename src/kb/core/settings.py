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
