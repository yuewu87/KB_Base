"""vault 的读写：文件、frontmatter、路径解析。

只管文件与数据，不做任何判断——归类在 classify、编排在 organize。
"""

from __future__ import annotations

import random
import re
import subprocess
from datetime import datetime
from pathlib import Path

import frontmatter

from kb import proc
from kb.core.models import (
    K_ID,
    K_PROJECT,
    K_REVISE,
    K_SOURCE,
    K_STATUS,
    K_SUBMITTED_AT,
    K_SUPERSEDED,
    K_SUPERSEDED_BY,
    K_TOPIC,
    K_TYPE,
    Draft,
    NoteType,
)

# ---------------------------------------------------------------- 路径常量

INBOX = "_收件箱"
PENDING = "待归类"
INDEX = "_索引"
ATTACHMENTS = "_附件"
JOURNAL_DIR = "整理日志"

# 内置领域——`init_vault.py` 用它建目录。运行时的领域清单以磁盘为准。
SEED_DOMAINS = ["计算机", "艺术", "文学"]

# 机器目录前缀——一级目录里带这个前缀的不是领域
META_PREFIX = "_"

DRAFT_STATUS = "待整理"


# ---------------------------------------------------------------- 原子写

def atomic_write(path: Path, text: str) -> None:
    """先写临时文件再改名，避免中断时留下半个文件（Q45）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- 草稿

def new_draft_id(now: datetime | None = None) -> str:
    """`YYYYMMDD-` + 4 位随机十六进制（Q55）。"""
    now = now or datetime.now()
    return f"{now:%Y%m%d}-{random.randrange(16 ** 4):04x}"


def draft_path(vault_root: Path, draft_id: str) -> Path:
    return vault_root / INBOX / f"{draft_id}.md"


def _optional_str(value: object) -> str | None:
    """YAML 里可能给出非字符串（如 `项目: 123`），统一成 str 或 None。

    不加这层，注解写的 `str | None` 就是假话，坏值会一路漏进 frozen 的 Draft，
    再没有校验机会。
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def write_draft(vault_root: Path, draft: Draft) -> Path:
    """把草稿落进收件箱。正文原样写入，不改写（Q55）。

    id 已存在时**抛 FileExistsError，不覆盖**。4 位随机十六进制只有 65536 种，
    长期使用撞号并非不可能——静默覆盖就是数据丢失，必须响亮失败。
    """
    path = draft_path(vault_root, draft.id)
    if path.exists():
        raise FileExistsError(f"草稿 id 冲突，拒绝覆盖：{path.name}")

    meta = {
        K_STATUS: DRAFT_STATUS,
        K_ID: draft.id,
        K_SUBMITTED_AT: draft.created_at,
    }
    if draft.source:
        meta[K_SOURCE] = draft.source
    if draft.project:
        meta[K_PROJECT] = draft.project
    if draft.revise_target:
        meta[K_REVISE] = draft.revise_target

    post = frontmatter.Post(draft.body, **meta)
    atomic_write(path, frontmatter.dumps(post, allow_unicode=True))
    return path


def read_draft(path: Path) -> Draft:
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    return Draft(
        id=str(post.get(K_ID) or path.stem),
        body=post.content,
        source=_optional_str(post.get(K_SOURCE)),
        project=_optional_str(post.get(K_PROJECT)),
        created_at=str(post.get(K_SUBMITTED_AT) or ""),
        revise_target=_optional_str(post.get(K_REVISE)),
    )


def list_drafts(vault_root: Path) -> list[Path]:
    """列出所有待整理草稿：收件箱根目录 + 待归类子目录（Q55）。

    待归类的也要扫，否则它们永远卡着——库长大之后原本归不了类的可能变得可归类。
    """
    inbox = vault_root / INBOX
    if not inbox.exists():
        return []
    paths = [p for p in inbox.glob("*.md") if p.is_file()]
    pending = inbox / PENDING
    if pending.exists():
        paths.extend(p for p in pending.glob("*.md") if p.is_file())
    return sorted(paths)


def find_draft(vault_root: Path, draft_id: str) -> Path | None:
    """按 id 找草稿。收件箱与待归类都会找。"""
    for path in list_drafts(vault_root):
        if path.stem == draft_id:
            return path
    return None


def move_to_pending(vault_root: Path, path: Path) -> Path:
    """把归不了类的草稿移进 待归类/。已在其中则原样返回。"""
    dest = vault_root / INBOX / PENDING / path.name
    if path.parent == dest.parent:
        return path
    dest.parent.mkdir(parents=True, exist_ok=True)
    path.replace(dest)
    return dest


def remove_draft(path: Path) -> None:
    """整理成功后删除草稿。"""
    path.unlink(missing_ok=True)


# ---------------------------------------------------------------- 笔记

def read_note(path: Path) -> tuple[dict, str]:
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    return dict(post.metadata), post.content


def write_note(path: Path, metadata: dict, body: str) -> None:
    """写笔记。metadata 里值为 None 的键会被丢掉——不写 `键: null`。"""
    clean = {k: v for k, v in metadata.items() if v is not None}
    post = frontmatter.Post(body, **clean)
    atomic_write(path, frontmatter.dumps(post, allow_unicode=True))


def first_heading(body: str) -> str:
    """取正文第一个 `# ` 标题；没有就用首个非空行。

    笔记的「一句话结论」就写在第一个标题里——**这才是它的标题**，
    文件名只是它的退化形式。候选召回（查重）和检索（显示）都要它，
    所以放在这里而不是各自的模块里。
    """
    for line in body.splitlines():
        if line.strip().startswith("# "):
            return line.strip()[2:].strip()
    for line in body.splitlines():
        if line.strip():
            return line.strip()
    return ""


def note_title(path: Path, body: str) -> str:
    """笔记对外显示的标题：正文里的一级标题，没有就退回文件名。"""
    return first_heading(body) or path.stem


def list_notes(vault_root: Path) -> list[Path]:
    """列出正式笔记（各领域下的全部 *.md）。

    不含 `_索引/`——索引页与整理日志是结构性文件，不是知识笔记。
    """
    found: list[Path] = []
    for name in list_domains(vault_root):
        found.extend(p for p in (vault_root / name).rglob("*.md") if p.is_file())
    return sorted(found)


def list_domains(vault_root: Path) -> list[str]:
    """vault 一级目录里的领域名。

    机器目录（`_` 前缀）与隐藏目录（`.` 前缀）不算领域。
    """
    if not vault_root.exists():
        return []
    return sorted(
        p.name
        for p in vault_root.iterdir()
        if p.is_dir() and not p.name.startswith((META_PREFIX, "."))
    )


def list_classifications(vault_root: Path, domain: str) -> list[str]:
    """某个领域下已有的分类目录（相对领域根的路径，递归）。"""
    root = vault_root / domain
    if not root.is_dir():
        return []
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_dir()
    )


# ---------------------------------------------------------------- 修改与失效（Q59/Q60）

def find_note_by_stem(vault_root: Path, stem: str) -> Path | None:
    """全库按文件名（不含 .md）搜唯一匹配。找不到或有多个 → None，不猜。"""
    if not stem:
        return None
    matches = [p for p in list_notes(vault_root) if p.stem == stem]
    return matches[0] if len(matches) == 1 else None


def is_superseded(meta: dict) -> bool:
    return bool(meta.get(K_SUPERSEDED))


def mark_superseded(path: Path, by: str) -> None:
    """把一篇笔记标记失效。正文一个字节不动——「当初为什么那么想」比结论有用。"""
    meta, body = read_note(path)
    meta[K_SUPERSEDED] = True
    meta[K_SUPERSEDED_BY] = by
    write_note(path, meta, body)


# ---------------------------------------------------------------- 项目名（Q30）


def project_name_from_cwd(cwd: Path) -> str | None:
    """取 git 仓库根的目录名作为项目名（Q30）。

    用 git 根而非 cwd 本身——agent 可能停在子目录（如 `src/kb/core/`），
    那样 basename 会取到 `core`。非 git 仓库回退到 cwd 的 basename。
    """
    try:
        # 返回值不能叫 `proc`——那会遮住上面 import 进来的 `kb.proc`
        # （`creationflags=proc.NO_CONSOLE` 当场 UnboundLocalError）。
        done = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=proc.NO_CONSOLE,  # 服务没有控制台，别给它闪一个（kb.proc）
        )
        if done.returncode == 0 and done.stdout.strip():
            return Path(done.stdout.strip()).name
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd.name or None


# ---------------------------------------------------------------- 索引页（Q56）

def topic_index_path(vault_root: Path, topic: str) -> Path:
    return vault_root / INDEX / f"{topic}.md"


def ensure_topic_index(vault_root: Path, topic: str) -> Path:
    """确保 `_索引/<领域>.md` 存在，返回其路径。

    索引页是**自动生成的 Dataview 查询页**，零维护——永远自动列出该领域下的所有笔记。
    它让「不允许孤儿笔记」（Q21）从空库第一天起就成立：第一条笔记就有东西可链。

    已存在则原样返回，**不覆盖**——用户可能自己改过。
    """
    path = topic_index_path(vault_root, topic)
    if path.exists():
        return path

    body = (
        f"# {topic}\n\n"
        "```dataview\n"
        "LIST\n"
        f'FROM "{topic}"\n'
        "SORT file.name ASC\n"
        "```\n"
    )
    write_note(path, {K_TYPE: NoteType.INDEX.value, K_TOPIC: [topic]}, body)
    return path


# ---------------------------------------------------------------- 文件名（Q72）

_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')
_TITLE_MAX = 60


def clean_title(raw: str) -> str:
    """把笔记标题清洗成合法文件名。非法或全空 → 抛 ValueError。

    规则见 `docs/01_架构.md` 第五节。
    """
    cleaned = _ILLEGAL_CHARS.sub("", raw).strip().rstrip(".")
    cleaned = cleaned[:_TITLE_MAX]
    if not cleaned:
        raise ValueError(f"标题清洗后为空：{raw!r}")
    return cleaned
