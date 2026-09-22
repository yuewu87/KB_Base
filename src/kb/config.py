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


class ConfigError(RuntimeError):
    """配置缺失或非法。"""


@dataclass(frozen=True)
class Config:
    # repr=False：key 不能进日志、终端或异常上下文
    llm_api_key: str = field(repr=False)
    llm_base_url: str
    llm_model: str
    # **`None` 表示「还没有知识库」**，不是「用默认的」。回落到一个写死的
    # 路径就是「别人的服务写进作者的库」，见 `require_vault`。
    vault_path: Path | None
    port: int | None
    # 下面这些有默认值——老 `.env` 不改也能跑起来（它们以前是硬编码常量）
    log_level: str = "INFO"
    sweep_interval_days: int = 6
    keep_days: int = 90
    # 界面皮肤。取值清单在 `kb.web.skins`，这里只做容错回落——
    # 不 import skins，免得 config 反过来依赖 web 层
    skin: str = "archive"


# 没有知识库时，每条路都用这一句。**说全两步，顺序也不能反**——
# `scripts/init_vault.py` 只建目录，**它不写 `.env`**（写配置一直是服务的活），
# 而且它**只认命令行给的路径、不读 `.env`**。原来这句写的是「填好 .env 再跑
# 脚本」，照做的人会在脚本的默认路径上建库、而 `.env` 指着别处——正是这句
# 文案本来要避免的半截状态。脚本的路径现在必填了，这句也照实写。
# 文案必须 GBK 可编码：中文 Windows 的控制台与管道都是 GBK，编不出来的字符
# 会抛 UnicodeEncodeError（`tests/test_architecture.py` 守着这条）。
NO_VAULT_MESSAGE = (
    "还没有知识库。请在网页上点「初始化知识库」，"
    "或跑 python scripts/init_vault.py <路径> 建好骨架、"
    "再把该路径填进 .env 的 KB_VAULT_PATH"
)


def require_vault(cfg: Config) -> Path:
    """拿生效的 vault 路径。没配就抛 `ConfigError`。

    **空值表示「没有」，不表示「用作者本机那个」。** 原来这里回落到一个写死的
    `E:\\KB_Library`——别人的服务会安安静静地写进作者的库，而且看起来一切正常
    （`list_drafts` / `list_domains` 在目录不存在时都静默返回 `[]`）。
    这是设计里点名要先拆的雷，见 spec 第三节。
    """
    if cfg.vault_path is None:
        raise ConfigError(NO_VAULT_MESSAGE)
    return cfg.vault_path


# 日志级别只认这两个。写别的（手改 `.env`）会在 `logging.setLevel` 上抛
# `ValueError`——那就成了一个「文件改了、内存没换、客户端拿 500」的怪状态。
_VALID_LOG_LEVELS = ("INFO", "DEBUG")


def _log_level(values: Mapping) -> str:
    """日志级别只认 INFO / DEBUG——写别的（手改 .env）会让 `setLevel` 抛，
    那就成了一个「文件改了、内存没换、客户端拿 500」的怪状态。
    """
    raw = str(values.get("KB_LOG_LEVEL") or "").strip().upper()
    return raw if raw in _VALID_LOG_LEVELS else "INFO"


# 皮肤名的合法清单。**故意在这里抄一份而不是 import `kb.web.skins`**：
# `config` 是被所有东西依赖的最底层，不该反过来依赖 web 层。
# 抄漏了有测试守着（`tests/test_config.py` 对着 `skins.SKIN_IDS` 核）。
_VALID_SKINS = ("archive", "dark-pink", "aurora", "garnet", "neon", "mono")


def _skin(values: Mapping) -> str:
    """皮肤名只认清单里的——手改 `.env` 写错不能让服务崩，
    回落 `archive` 跑着，界面上显示默认值，人一看就知道不对。

    和 `_log_level` 是同一条理由：`reload_config` 里那个「文件改了、内存没换」
    的怪状态，比一份不完整的配置难查得多。
    """
    raw = str(values.get("KB_SKIN") or "").strip().lower()
    return raw if raw in _VALID_SKINS else "archive"


def _int_or(values: Mapping, key: str, default: int) -> int:
    """读一个正整数配置。**读不出来就静默回默认值。**

    静默是有意的：配置坏了不该让服务起不来，用默认值跑着，
    界面上那个字段会显示默认值，人一看就知道不对。
    """
    raw = str(values.get(key) or "").strip()
    try:
        number = int(raw)
    except ValueError:
        return default
    return number if number > 0 else default


def _build(get: Mapping, *, strict: bool = True) -> Config:
    """从一份键值里造 Config。缺必填项时抛 ConfigError。

    `strict=False` 时缺的必填项置空字符串（`reload_config` 的退路用）——
    **只有热重载才这么造**，启动路径必须严格，否则 key 没填也能起来。
    """

    def required(key: str) -> str:
        value = str(get.get(key) or "").strip()
        if not value and strict:
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
        vault_path=Path(vault_raw) if vault_raw else None,
        port=int(port_raw) if port_raw.isdigit() else None,
        log_level=_log_level(get),
        sweep_interval_days=_int_or(get, "KB_SWEEP_INTERVAL", 6),
        keep_days=_int_or(get, "KB_LOG_KEEP_DAYS", 90),
        skin=_skin(get),
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
       重载会变成空转。
    2. 重载不该污染进程环境。它是「读文件造一份新的」，不是「改环境」。

    文件不存在、或必填项被手滑删掉时，用默认值造一份，**不抛**——
    别把正在跑的服务带崩。

    另注：`load_dotenv`（override=False）是**环境变量赢**，而这里是**文件赢**。
    热重载要的就是文件赢（用户在网页上刚改的），但同一份 `.env` 经两条路
    读出来可能不同——排查配置问题时先想起这件事。
    """
    env_file = env_file or PROJECT_ROOT / ".env"
    try:
        values: Mapping = dotenv_values(env_file) if env_file.is_file() else {}
    except (OSError, UnicodeDecodeError):
        # 文件坏了（编码不对、读不了）——当读不到处理，别把正在跑的服务带崩
        values = {}
    try:
        return _build(values)
    except ConfigError:
        # 必填项缺了（文件不在，或被手滑删掉）：退回不严格模式，
        # 缺的置空、能读的照读。**不抛**——重载是服务在跑的时候发生的，
        # 这里抛出去就是把正在跑的服务带崩，代价远大于一份不完整的配置。
        return _build(values, strict=False)
