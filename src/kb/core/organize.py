"""整理编排：三段式的第三段（落盘）与整体调度。

① 规划：build_messages → llm.complete → parse_plan
② 校验：validate_plan（纯静态，不过就打回，vault 未动）
③ 落盘：本模块。**不调 LLM**，纯文件操作，确定、快、可回滚

按条隔离（Q45）：一条失败不影响其他条，失败那条什么也不写（所以重试天然幂等）。
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path

from kb.core import planning
from kb.core.classify import find_candidates, knowledge_topics
from kb.core.journal import append_results
from kb.core.models import (
    K_CREATED,
    K_TOPIC,
    K_UPDATED,
    Draft,
    OrganizePlan,
    OrganizeResult,
    Outcome,
    ResultKind,
)
from kb.core.planning import PlanError
from kb.core.vault import (
    ensure_topic_index,
    list_drafts,
    move_to_pending,
    read_draft,
    read_note,
    topic_index_path,
    write_note,
)
from kb.llm.base import LLM, LLMError

SERVICE_AUTHOR_NAME = "kb-service"
SERVICE_AUTHOR_EMAIL = "kb-service@localhost"

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 2)


# ------------------------------------------------------------ 事务

class Transaction:
    """记录本次操作动过的文件，失败时**精确**回滚（Q45）。

    绝不能用 `git checkout .`——那会把用户尚未提交的改动一起还原掉。
    """

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root
        self._originals: dict[Path, bytes | None] = {}

    def _remember(self, path: Path) -> None:
        if path not in self._originals:
            # None 表示「本来不存在」——回滚时删掉即可
            self._originals[path] = path.read_bytes() if path.exists() else None

    def touch_create(self, path: Path) -> None:
        self._remember(path)

    def touch_modify(self, path: Path) -> None:
        self._remember(path)

    def touch_delete(self, path: Path) -> None:
        self._remember(path)

    @property
    def touched(self) -> list[Path]:
        return sorted(self._originals)

    def rollback(self) -> None:
        for path, original in self._originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)


# ------------------------------------------------------------ 落盘辅助

def _write_note_safe(path: Path, meta: dict, body: str) -> None:
    """单独抽出来便于测试注入失败。"""
    write_note(path, meta, body)


def _today(when: datetime | None) -> str:
    return f"{(when or datetime.now()):%Y-%m-%d}"


def _ensure_indexes(vault_root: Path, plan: OrganizePlan, txn: Transaction) -> None:
    """确保引用的主题索引页存在——让第一条笔记就有东西可链（Q21）。

    只处理**已存在**的主题；不存在的主题是校验阶段就该拦下的（Q11）。
    """
    topics = plan.frontmatter.get(K_TOPIC) or []
    if isinstance(topics, str):
        topics = [topics]

    known = set(knowledge_topics(vault_root))
    for topic in topics:
        if topic not in known:
            continue
        idx = topic_index_path(vault_root, topic)
        if not idx.exists():
            txn.touch_create(idx)
            ensure_topic_index(vault_root, topic)


# ------------------------------------------------------------ 第三段：落盘

def apply_plan(
    vault_root: Path,
    draft_path: Path,
    plan: OrganizePlan,
    txn: Transaction,
    when: datetime | None = None,
) -> OrganizeResult:
    """按计划落盘。不调 LLM——所以慢不了，也几乎不会失败。"""
    if plan.outcome is Outcome.PENDING:
        move_to_pending(vault_root, draft_path)
        return OrganizeResult(
            draft_id=plan.draft_id,
            kind=ResultKind.PENDING,
            detail=plan.pending_reason or "无法归类",
        )

    assert plan.target_path is not None      # 已在 validate_plan 保证
    target = vault_root / plan.target_path

    # 「用户的判断」只由用户本人填写（Q23），这里机械清空——不靠模型自觉
    body_content = planning.strip_user_judgment(plan.content)

    if plan.outcome is Outcome.CREATE:
        txn.touch_create(target)
        meta = dict(plan.frontmatter)
        meta.setdefault(K_CREATED, _today(when))
        meta[K_UPDATED] = _today(when)
        _write_note_safe(target, meta, body_content)
        _ensure_indexes(vault_root, plan, txn)
        kind = ResultKind.CREATED
    else:
        txn.touch_modify(target)
        meta, body = read_note(target)
        meta[K_UPDATED] = _today(when)
        body = body.rstrip("\n") + "\n\n" + body_content.strip() + "\n"
        _write_note_safe(target, meta, body)
        kind = ResultKind.FOLDED

    txn.touch_delete(draft_path)
    draft_path.unlink(missing_ok=True)

    return OrganizeResult(
        draft_id=plan.draft_id,
        kind=kind,
        detail=f"[[{target.stem}]]（{plan.target_path}）",
    )


# ------------------------------------------------------------ 第一、二段：规划

def _complete(vault_root: Path, draft: Draft, llm: LLM, hint: str | None) -> str:
    messages = planning.build_messages(
        draft,
        find_candidates(vault_root, draft.body),
        knowledge_topics(vault_root),
        vault_root,
    )
    user = messages[1]["content"]
    if hint:
        user += f"\n\n## 上次尝试失败的原因\n{hint}\n请修正后重新只输出 JSON。"
    return llm.complete(messages[0]["content"], user)


def make_plan(
    vault_root: Path,
    draft: Draft,
    llm: LLM,
    sleep=time.sleep,
    max_attempts: int = MAX_ATTEMPTS,
) -> OrganizePlan:
    """规划 + 校验。任一环节失败都抛 PlanError / LLMError。

    两类失败分开处理：网络类直接退避重试（模型没问题）；格式类把错误信息
    喂回给模型让它自己修——比单纯重试有效得多。
    """
    hint: str | None = None
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        if attempt:
            sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
        try:
            raw = _complete(vault_root, draft, llm, hint)
            plan = planning.parse_plan(draft.id, raw)
            planning.validate_plan(plan, vault_root)
            return plan
        except LLMError as exc:
            last_error = exc                       # 网络类：直接重试
        except PlanError as exc:
            last_error = exc
            hint = str(exc)                        # 格式类：把错误喂回去让它自己修

    raise PlanError(f"规划失败（尝试 {max_attempts} 次）：{last_error}")


# ------------------------------------------------------------ 单条编排

def organize_draft(
    vault_root: Path,
    draft_path: Path,
    llm: LLM,
    when: datetime | None = None,
    sleep=time.sleep,
) -> tuple[OrganizeResult, list[Path]]:
    """整理一条草稿。返回 (结果, 本次动过的文件)。

    失败时**什么也不写**——草稿原样留在收件箱，所以重试天然幂等。
    """
    draft = read_draft(draft_path)

    try:
        plan = make_plan(vault_root, draft, llm, sleep=sleep)
    except (PlanError, LLMError) as exc:
        return (
            OrganizeResult(
                draft_id=draft.id,
                kind=ResultKind.FAILED,
                detail="规划失败",
                error=str(exc),
            ),
            [],
        )

    txn = Transaction(vault_root)
    try:
        result = apply_plan(vault_root, draft_path, plan, txn, when)
    except Exception as exc:  # noqa: BLE001 —— 落盘要兜住一切并回滚
        txn.rollback()
        return (
            OrganizeResult(
                draft_id=draft.id,
                kind=ResultKind.FAILED,
                detail="落盘失败，已回滚",
                error=str(exc),
            ),
            [],
        )

    return result, txn.touched


# ------------------------------------------------------------ 批量编排

def organize_selected(
    vault_root: Path,
    paths: list[Path],
    llm: LLM,
    when: datetime | None = None,
    sleep=time.sleep,
    commit: bool = True,
) -> list[OrganizeResult]:
    """整理指定的若干条草稿，按条隔离（Q45）。

    `organize_all`（全部）与「只整理某一条」（Q38）共用这一份收尾逻辑——
    否则两条路径会各自实现「写日志 + 提交」，迟早对不上。
    """
    when = when or datetime.now()
    results: list[OrganizeResult] = []
    touched: list[Path] = []

    for path in paths:
        result, paths_touched = organize_draft(vault_root, path, llm, when, sleep)
        results.append(result)
        touched.extend(paths_touched)

    if not results:
        return results

    journal_path = append_results(vault_root, results, when)
    if journal_path is not None:
        touched.append(journal_path)

    if commit:
        commit_changes(vault_root, touched, results, when)

    return results


def organize_all(
    vault_root: Path,
    llm: LLM,
    when: datetime | None = None,
    sleep=time.sleep,
    commit: bool = True,
) -> list[OrganizeResult]:
    """整理收件箱里的全部草稿（含待归类），按条隔离。"""
    return organize_selected(vault_root, list_drafts(vault_root), llm, when, sleep, commit)


# ------------------------------------------------------------ git（Q46）

def build_commit_message(
    results: list[OrganizeResult], when: datetime | None = None
) -> str:
    ok = [r for r in results if r.kind in (ResultKind.CREATED, ResultKind.FOLDED)]
    lines = [f"整理草稿 {len(ok)} 条", ""]

    for r in ok:
        verb = "新建" if r.kind is ResultKind.CREATED else "合并入"
        lines.append(f"- {verb} {r.detail}")

    pending = sum(1 for r in results if r.kind is ResultKind.PENDING)
    failed = sum(1 for r in results if r.kind is ResultKind.FAILED)
    if pending:
        lines.append(f"- 待归类 {pending} 条")
    if failed:
        lines.append(f"- 失败 {failed} 条")

    return "\n".join(lines).rstrip() + "\n"


def _git(vault_root: Path, *args: str) -> subprocess.CompletedProcess:
    """调用 git。

    **必须显式指定 utf-8 与 errors="replace"。** Windows 下 `text=True` 会按
    本地编码（GBK）解码，而 git 输出（中文 commit message、路径）是 UTF-8——
    解码异常抛在子进程的读取线程里，主流程只看到 `stdout=None`，极难排查。
    """
    return subprocess.run(
        ["git", *args],
        cwd=vault_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _stageable(vault_root: Path, rels: list[str]) -> list[str]:
    """筛掉 git 处理不了的路径。

    **草稿是这里的关键**：它由 `/push` 写入、`/push` 不提交，所以整理时还是个
    未跟踪文件；整理成功后又会被删掉。此时 `git add -- 00_收件箱/xxx.md` 会报
    `pathspec did not match any files`——而 **git add 只要有一个 pathspec 失败就
    整体放弃**，结果是一个文件都进不去、commit 根本不会发生。

    保留规则：磁盘上还在的（新增/修改），或者已被跟踪的（删除）。
    两者都不是的（从未跟踪、现已消失）跳过。
    """
    if not rels:
        return []
    tracked = set(_git(vault_root, "ls-files", "-z", "--", *rels).stdout.split("\0"))
    return [r for r in rels if (vault_root / r).exists() or r in tracked]


def commit_changes(
    vault_root: Path,
    touched: list[Path],
    results: list[OrganizeResult],
    when: datetime | None = None,
) -> bool:
    """一次整理 = 一个 commit（Q46）。

    **只 add 自己动过的文件**——禁用 `git add -A`，否则会把用户正在编辑、
    尚未提交的笔记一起裹进这次「AI 整理」的 commit，历史就骗人了。
    """
    rels: list[str] = []
    for path in touched:
        try:
            rels.append(path.relative_to(vault_root).as_posix())
        except ValueError:
            continue

    rels = _stageable(vault_root, rels)
    if not rels:
        return False

    _git(vault_root, "add", "--", *rels)
    proc = _git(
        vault_root,
        "-c", f"user.name={SERVICE_AUTHOR_NAME}",
        "-c", f"user.email={SERVICE_AUTHOR_EMAIL}",
        "commit", "-m", build_commit_message(results, when),
    )
    return proc.returncode == 0
