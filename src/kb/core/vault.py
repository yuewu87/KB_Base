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

from kb.core.models import (
    K_ID,
    K_PROJECT,
    K_SOURCE,
    K_STATUS,
    K_SUBMITTED_AT,
    K_TOPIC,
    K_TYPE,
    Draft,
    NoteType,
)

INBOX = "00_收件箱"
PENDING = "待归类"
PROJECTS = "10_项目"
KNOWLEDGE = "20_知识"
MATERIALS = "30_素材"
INDEX = "40_索引"
ATTACHMENTS = "90_附件"

DRAFT_STATUS = "待整理"

_SEPARATOR_RE = re.compile(r"[-_\s]+")


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


def list_notes(vault_root: Path) -> list[Path]:
    """列出正式笔记（项目档案 + 知识区），供查重预筛取候选。

    不含 `40_索引/`——索引页与整理日志是结构性文件，不是知识笔记。
    """
    found: list[Path] = []
    for folder in (vault_root / PROJECTS, vault_root / KNOWLEDGE):
        if folder.exists():
            found.extend(p for p in folder.rglob("*.md") if p.is_file())
    return sorted(found)


# ---------------------------------------------------------------- 项目名（Q30）

def normalize_project(name: str) -> str:
    """项目名规范化：转小写，`-`、`_`、空格视为等价。

    避免 `KN_Base` / `kn_base` / `KN-Base` 被当成三个项目。
    """
    return _SEPARATOR_RE.sub("-", name.strip().lower())


def find_project_dir(vault_root: Path, name: str) -> Path | None:
    """在 `10_项目/<分组>/<项目名>` 下搜唯一匹配。

    找不到或有多个同名 → 返回 None（不猜，走待归类）。
    """
    if not name:
        return None
    root = vault_root / PROJECTS
    if not root.exists():
        return None

    target = normalize_project(name)
    matches: list[Path] = []
    for group in sorted(root.iterdir()):
        if not group.is_dir():
            continue
        for project in sorted(group.iterdir()):
            if project.is_dir() and normalize_project(project.name) == target:
                matches.append(project)
    return matches[0] if len(matches) == 1 else None


def list_projects(vault_root: Path) -> list[tuple[str, Path]]:
    """列出 `10_项目/<分组>/<项目名>` 下的所有项目，返回 (分组名, 项目路径)。"""
    root = vault_root / PROJECTS
    if not root.exists():
        return []
    found: list[tuple[str, Path]] = []
    for group in sorted(root.iterdir()):
        if not group.is_dir():
            continue
        for project in sorted(group.iterdir()):
            if project.is_dir():
                found.append((group.name, project))
    return found


def project_name_from_cwd(cwd: Path) -> str | None:
    """取 git 仓库根的目录名作为项目名（Q30）。

    用 git 根而非 cwd 本身——agent 可能停在子目录（如 `src/kb/core/`），
    那样 basename 会取到 `core`。非 git 仓库回退到 cwd 的 basename。
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip()).name
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd.name or None


# ---------------------------------------------------------------- 索引页（Q56）

def topic_index_path(vault_root: Path, topic: str) -> Path:
    return vault_root / INDEX / f"{topic}.md"


def ensure_topic_index(vault_root: Path, topic: str) -> Path:
    """确保 `40_索引/<主题>.md` 存在，返回其路径。

    索引页是**自动生成的 Dataview 查询页**，零维护——永远自动列出该主题下的所有笔记。
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
        f'FROM "{KNOWLEDGE}/{topic}"\n'
        "SORT file.name ASC\n"
        "```\n"
    )
    write_note(path, {K_TYPE: NoteType.INDEX.value, K_TOPIC: [topic]}, body)
    return path
