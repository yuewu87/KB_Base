"""会话的存与读。

**存服务侧，不入库。** 代码仓库是 public 的——会话历史进去就等于公开发布。
代价：换机器时它不跟着 git 走，得手动拷 `data/chats/`。

**它不是知识**，所以按 Q80 的分界（「是不是知识」）不进 vault。

## ⚠️ 所有函数的第一个参数是 `data_dir`，不是 `project_root`

传 `config.DATA_DIR`（= `<root>/data`），**不要传 `PROJECT_ROOT`**——那样会话会
落到仓库根的 `chats/`，而**那条路径没被 gitignore 覆盖**，会直接进 public 仓库。

测试里传 `tmp_path` 是安全的（临时目录本来就不入库）。
"""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path

from kb.config import DATA_DIR, PROJECT_ROOT

CHATS = "chats"
_MSG_LIMIT = 200          # 一个会话最多留这么多条，防无限长


def chats_dir(data_dir: Path) -> Path:
    """会话目录。**落点如果在本仓库里，必须在 `data/` 下。**

    传 `PROJECT_ROOT` 就会落成 `<root>/chats/`——那条路径**没被 gitignore 覆盖**，
    会直接进 public 仓库。这里当场挡住，不靠调用方自觉。
    """
    path = data_dir / CHATS
    if path.is_relative_to(PROJECT_ROOT) and not path.is_relative_to(DATA_DIR):
        raise ValueError(
            f"会话目录落在仓库内但不在 data/ 下：{path}\n"
            "这会进 public 仓库。请传 config.DATA_DIR，不要传 PROJECT_ROOT。"
        )
    return path


def chat_path(data_dir: Path, chat_id: str) -> Path:
    return chats_dir(data_dir) / f"{chat_id}.json"


def new_chat_id(now: datetime | None = None) -> str:
    """`YYYYMMDD-` + 4 位随机十六进制。与草稿 id 同一套路。"""
    now = now or datetime.now()
    return f"{now:%Y%m%d}-{random.randrange(16 ** 4):04x}"


def load_chat(data_dir: Path, chat_id: str) -> dict | None:
    path = chat_path(data_dir, chat_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_chat(data_dir: Path, chat_id: str, messages: list[dict]) -> dict:
    """整篇写入。返回落盘的会话对象。"""
    first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
    chat = {
        "id": chat_id,
        "title": first_user.splitlines()[0][:40] if first_user else "（空会话）",
        "updated": f"{datetime.now():%Y-%m-%d %H:%M}",
        "messages": messages[-_MSG_LIMIT:],
    }
    directory = chats_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    chat_path(data_dir, chat_id).write_text(
        json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return chat


def append_message(data_dir: Path, chat_id: str, role: str, content: str) -> dict:
    """追加一条消息。会话不存在就新建。"""
    chat = load_chat(data_dir, chat_id)
    messages = chat["messages"] if chat else []
    messages.append({"role": role, "content": content})
    return save_chat(data_dir, chat_id, messages)


def list_chats(data_dir: Path) -> list[dict]:
    """全部会话，按 id 倒序（id 前缀是日期，所以等价于时间倒序）。"""
    directory = chats_dir(data_dir)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append({"id": data["id"], "title": data["title"], "updated": data["updated"]})
    return out
