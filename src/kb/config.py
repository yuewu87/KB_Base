"""读取工程根目录的 .env 配置。

配置集中在一个文件夹（Q32），不散到用户目录。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 本文件位于 <root>/src/kb/config.py，向上三层即工程根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

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


def load_config(env_file: Path | None = None) -> Config:
    """从 .env 读取配置。缺必填项时抛 ConfigError。

    注意：load_dotenv 会写入进程级 os.environ，所以**同一个进程内只应调用一次**。
    重复传入不同的 env_file 不会覆盖已设置的变量（override=False）。
    """
    env_file = env_file or PROJECT_ROOT / ".env"
    load_dotenv(env_file, override=False)

    def required(key: str) -> str:
        value = os.environ.get(key, "").strip()
        if not value:
            raise ConfigError(
                f"缺少必填配置 {key}。请复制 .env.example 为 .env 并填写。"
            )
        return value

    vault_raw = os.environ.get("KB_VAULT_PATH", "").strip()
    port_raw = os.environ.get("KB_PORT", "").strip()

    return Config(
        llm_api_key=required("KB_LLM_API_KEY"),
        llm_base_url=required("KB_LLM_BASE_URL"),
        llm_model=required("KB_LLM_MODEL"),
        vault_path=Path(vault_raw) if vault_raw else DEFAULT_VAULT_PATH,
        port=int(port_raw) if port_raw else None,
    )
