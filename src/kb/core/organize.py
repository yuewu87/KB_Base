"""整理编排：三段式的第三段（落盘）与整体调度。

① 规划：build_messages → llm.complete → parse_plan
② 校验：validate_plan（纯静态，不过就打回，vault 未动）
③ 落盘：本模块。**不调 LLM**，纯文件操作，确定、快、可回滚

按条隔离（Q45）：一条失败不影响其他条，失败那条什么也不写（所以重试天然幂等）。
"""

from __future__ import annotations

import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from kb.core import flow, planning, review
from kb.core.classify import find_candidates
from kb.core.journal import append_results
from kb.core.models import (
    K_CREATED,
    K_TOPIC,
    K_TYPE,
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
    find_note_by_stem,
    list_domains,
    list_drafts,
    mark_superseded,
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


def _ensure_indexes(vault_root: Path, topics: list[str], txn: Transaction) -> None:
    """确保引用的主题索引页存在——让第一条笔记就有东西可链（Q21）。

    只处理**已存在**的主题；不存在的主题是校验阶段就该拦下的（Q11）。
    """
    known = set(list_domains(vault_root))
    for topic in topics:
        if topic not in known:
            continue
        idx = topic_index_path(vault_root, topic)
        if not idx.exists():
            txn.touch_create(idx)
            ensure_topic_index(vault_root, topic)


# `## 相关` 是模板的收尾节。fold 追加的内容要排在它**前面**——
# 加在它后面等于把收尾节挤到文章中间（Q101 端到端跑出来的实例）。
_RELATED_RE = re.compile(r"^## 相关\s*$", re.M)


def _insert_before_related(body: str, chunk: str) -> str:
    """把 fold 的新章节插到 `## 相关` 之前，正文之后。

    找不到 `## 相关` 就照旧追加到末尾——那种笔记是用户自己改过的，
    别猜他想放哪。
    """
    body = body.rstrip("\n")
    match = _RELATED_RE.search(body)
    if match is None:
        return f"{body}\n\n{chunk}\n"
    # 拼之前先滤掉空段：正文是空的（笔记只有 `## 相关`）时，
    # 直接拼会拼出两个前导空行。
    parts = [body[: match.start()].strip("\n"), chunk, body[match.start():].strip("\n")]
    return "\n\n".join(p for p in parts if p) + "\n"


# ------------------------------------------------------------ 第三段：落盘

def apply_plan(
    vault_root: Path,
    draft_path: Path,
    draft: Draft,
    plan: OrganizePlan,
    txn: Transaction,
    when: datetime | None = None,
) -> OrganizeResult:
    """按计划落盘。不调 LLM——所以慢不了，也几乎不会失败。"""
    if plan.outcome is Outcome.PENDING:
        move_to_pending(vault_root, draft_path)
        reason = plan.pending_reason or "无法归类"
        # 这里是提前 return，流程链上也走到了终点——不记的话「落盘」
        # 永远显示未走到，看的人会以为卡住了
        flow.emit("落盘", f"归不了类，搁进待归类：{reason}")
        return OrganizeResult(
            draft_id=plan.draft_id,
            kind=ResultKind.PENDING,
            detail=reason,
        )

    assert plan.target_path is not None      # 已在 validate_plan 保证
    target = vault_root / plan.target_path

    if plan.outcome is Outcome.CREATE:
        txn.touch_create(target)
        # 主题/项目由这里算出来，不问模型——见 planning.resolve_frontmatter（Q101）
        meta = planning.resolve_frontmatter(plan, draft)
        meta.setdefault(K_CREATED, _today(when))
        meta[K_UPDATED] = _today(when)
        _write_note_safe(target, meta, plan.content)
        _ensure_indexes(vault_root, meta.get(K_TOPIC) or [], txn)
        kind = ResultKind.CREATED
    else:
        txn.touch_modify(target)
        meta, body = read_note(target)
        meta[K_UPDATED] = _today(when)
        body = _insert_before_related(body, plan.content.strip())
        _write_note_safe(target, meta, body)
        kind = ResultKind.FOLDED

    if plan.revise_target:
        old = find_note_by_stem(vault_root, plan.revise_target)
        if old is None:
            raise PlanError(
                f"--revise 指定的目标找不到或不唯一：{plan.revise_target}"
            )
        # 兜底：一份笔记不能声明被自己取代。validate_plan 已经拦了正常路径，
        # 这里防的是别处绕过校验直接落盘的调用（落成这个状态很难看出来）。
        if old == target:
            raise PlanError(
                f"修改请求的目标与被修订的笔记是同一篇：{plan.revise_target}"
            )
        txn.touch_modify(old)
        mark_superseded(old, by=Path(plan.target_path).stem)

    txn.touch_delete(draft_path)
    draft_path.unlink(missing_ok=True)

    verb = "新建" if plan.outcome is Outcome.CREATE else "并入"
    flow.emit("落盘", f"{verb} {plan.target_path}")

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
        list_domains(vault_root),
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
            plan.revise_target = draft.revise_target
            planning.validate_plan(plan, vault_root)
            note_type = plan.frontmatter.get(K_TYPE) or "未定"
            if plan.outcome is Outcome.PENDING:
                # **pending 没有 target_path。** 照原样打会印出
                # 「模型决定放进「None」，类型是未定」——工作日志页上就是一句
                # 废话（2026-09-17 端到端跑出来的）。
                flow.emit("规划", "模型判断这条归不了类")
            else:
                flow.emit(
                    "规划",
                    f"模型决定放进「{plan.target_path}」，类型是{note_type}",
                )
            flow.emit("校验", "校验通过")
            planned_path = plan.target_path
            plan = review.review_plan(plan, vault_root, llm)
            if plan.target_path != planned_path:
                flow.emit("审核", f"审核觉得和已有分类重了，改用「{plan.target_path}」")
            planning.validate_plan(plan, vault_root)      # 审核的输出也要过静态校验
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
        result = apply_plan(vault_root, draft_path, draft, plan, txn, when)
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
    run_id: str | None = None,
) -> list[OrganizeResult]:
    """整理指定的若干条草稿，按条隔离（Q45）。

    `organize_all`（全部）与「只整理某一条」（Q38）共用这一份收尾逻辑——
    否则两条路径会各自实现「写日志 + 提交」，迟早对不上。
    """
    when = when or datetime.now()

    # **一批一个新 run**，在这儿设而不是在端点里——入口有三个
    # （`/organize`、Web 投递的 `push_and_organize`、对话的 organize 动作），
    # 在端点里设的话另外两条路的流程会全挤进「未分组」互相串。
    #
    # `run_id` 由调用方给：Web 投递要把它那次「投递」和随后的整理串成同一个
    # run，所以先设好再传进来。
    flow.set_run(run_id or flow.new_run_id(when))
    if paths:
        flow.emit("投递", f"开始整理，共 {len(paths)} 条草稿")

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


def git_run(vault_root: Path, *args: str) -> subprocess.CompletedProcess:
    """调用 git。

    **公开**（不带下划线）：巡检那边（`api/http.py` 的 `_commit_sweep`）也用它。
    编码与 `-c core.quotepath` 这些平台坑**只该有一处实现**，复制一份迟早改漏。

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


def stageable(vault_root: Path, rels: list[str]) -> list[str]:
    """筛掉 git 处理不了的路径。

    **公开**：理由同 `git_run`——巡检与整理共用这一份。

    **草稿是这里的关键**：它由 `/push` 写入、`/push` 不提交，所以整理时还是个
    未跟踪文件；整理成功后又会被删掉。此时 `git add -- 00_收件箱/xxx.md` 会报
    `pathspec did not match any files`——而 **git add 只要有一个 pathspec 失败就
    整体放弃**，结果是一个文件都进不去、commit 根本不会发生。

    保留规则：磁盘上还在的（新增/修改），或者已被跟踪的（删除）。
    两者都不是的（从未跟踪、现已消失）跳过。
    """
    if not rels:
        return []
    tracked = set(git_run(vault_root, "ls-files", "-z", "--", *rels).stdout.split("\0"))
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

    rels = stageable(vault_root, rels)
    if not rels:
        return False

    message = build_commit_message(results, when)
    git_run(vault_root, "add", "--", *rels)
    proc = git_run(
        vault_root,
        "-c", f"user.name={SERVICE_AUTHOR_NAME}",
        "-c", f"user.email={SERVICE_AUTHOR_EMAIL}",
        "commit", "-m", message,
    )
    if proc.returncode == 0:
        flow.emit("提交", f"提交了一个 commit：「{message.splitlines()[0]}」")
    return proc.returncode == 0
