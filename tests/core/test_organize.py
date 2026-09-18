import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from kb.core import organize
from kb.core.models import Draft, OrganizeResult, ResultKind
from kb.core.vault import (
    ATTACHMENTS,
    INDEX,
    PENDING,
    list_drafts,
    read_note,
    write_draft,
    write_note,
)
from kb.llm.base import LLM, FakeLLM, LLMError

WHEN = datetime(2026, 9, 15, 14, 32)
NO_SLEEP = staticmethod(lambda _seconds: None)

DRAFT = Draft(
    id="20260915-a3f2",
    body="并发写入会锁表，最后用队列串行化解决",
    source="会话",
    project=None,
    created_at="2026-09-15 14:32",
)


def _plan_json(**overrides) -> str:
    data = {
        "outcome": "create",
        "target_path": "计算机/并发写锁.md",
        "frontmatter": {"类型": "概念", "主题": ["计算机"]},
        "content": "# 并发写锁\n\n见 [[计算机]]\n",
        "pending_reason": None,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _git(vault: Path, *args: str) -> subprocess.CompletedProcess:
    """测试里调 git。

    两处必须显式指定：
    - `encoding="utf-8"`：Windows 下 text=True 按 GBK 解码，中文路径/commit
      message 会炸在子进程读取线程里，主流程只看到 stdout=None。
    - `core.quotepath=false`：否则 git 把中文路径转成八进制转义
      （`"20_\\347\\237\\245..."`），按字面比对全部对不上。
    """
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=vault,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / "计算机").mkdir(parents=True)
    _git(tmp_path, "init", "-b", "main")
    _git(
        tmp_path,
        "-c", "user.name=t", "-c", "user.email=t@x",
        "commit", "--allow-empty", "-m", "init",
    )
    return tmp_path


def _run(vault: Path, llm: LLM, **kw):
    path = write_draft(vault, DRAFT)
    return organize.organize_draft(vault, path, llm, when=WHEN, sleep=NO_SLEEP, **kw)


# ---------- 成功路径 ----------

def test_create_writes_note_and_removes_draft(vault):
    result, _ = _run(vault, FakeLLM(_plan_json()))

    assert result.kind is ResultKind.CREATED
    note = vault / "计算机" /"并发写锁.md"
    assert note.exists()

    meta, body = read_note(note)
    assert meta["类型"] == "概念"
    assert meta["主题"] == ["计算机"]
    assert "见 [[计算机]]" in body

    assert list_drafts(vault) == []      # 草稿已消费


def test_create_ensures_topic_index_page(vault):
    """空库第一天：索引页由服务自动建，第一条笔记才有东西可链（Q21）。"""
    _run(vault, FakeLLM(_plan_json()))
    idx = vault / INDEX / "计算机.md"
    assert idx.exists()
    assert "索引" in idx.read_text(encoding="utf-8")


def test_create_does_not_touch_existing_index_page(vault):
    idx = vault / INDEX / "计算机.md"
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text("用户自己写的", encoding="utf-8")
    _run(vault, FakeLLM(_plan_json()))
    assert idx.read_text(encoding="utf-8") == "用户自己写的"


def test_create_sets_timestamps(vault):
    _run(vault, FakeLLM(_plan_json()))
    meta, _ = read_note(vault / "计算机" /"并发写锁.md")
    assert meta["创建"] == "2026-09-15"
    assert meta["更新"] == "2026-09-15"


# ---------- 字段归属：主题与项目归代码（Q101）----------

def test_create_derives_topic_from_the_path_not_from_the_model(vault):
    """标签是路径派生出来的，模型填什么都覆盖掉（Q101）。"""
    _run(vault, FakeLLM(_plan_json(
        frontmatter={"类型": "概念", "主题": ["模型自己填的"]},
    )))
    meta, _ = read_note(vault / "计算机" /"并发写锁.md")
    assert meta["主题"] == ["计算机"]


def test_create_puts_path_dirs_before_semantic_tags(vault):
    _run(vault, FakeLLM(_plan_json(semantic_tags=["版本控制", "Git 操作"])))
    meta, _ = read_note(vault / "计算机" /"并发写锁.md")
    assert meta["主题"] == ["计算机", "版本控制", "git-操作"]


def test_create_writes_the_draft_project_even_when_the_model_omits_it(vault):
    """实测四篇笔记的 `项目` 丢了——草稿里明明有，模型漏填、校验不管（Q101）。"""
    draft = Draft(
        id=DRAFT.id, body=DRAFT.body, source="会话",
        project="KN_Base", created_at=DRAFT.created_at,
    )
    path = write_draft(vault, draft)
    organize.organize_draft(vault, path, FakeLLM(_plan_json()), when=WHEN, sleep=NO_SLEEP)

    meta, _ = read_note(vault / "计算机" /"并发写锁.md")
    assert meta["项目"] == "KN_Base"


def test_create_drops_a_project_the_model_invented(vault):
    """草稿没有项目（Web 投递）时，模型自己编的不许写进去。"""
    _run(vault, FakeLLM(_plan_json(
        frontmatter={"类型": "概念", "项目": "模型编的项目"},
    )))
    meta, _ = read_note(vault / "计算机" /"并发写锁.md")
    assert "项目" not in meta


def test_create_result_detail_links_to_note(vault):
    result, _ = _run(vault, FakeLLM(_plan_json()))
    assert "[[并发写锁]]" in result.detail


def test_fold_appends_to_existing_note(vault):
    target = vault / "计算机" /"队列串行化.md"
    write_note(target, {"类型": "概念", "主题": ["计算机"]}, "# 队列串行化\n\n原有内容\n")

    result, _ = _run(
        vault,
        FakeLLM(_plan_json(
            outcome="fold",
            target_path="计算机/队列串行化.md",
            content="补充：队列满时要限流\n",
        )),
    )

    assert result.kind is ResultKind.FOLDED
    _, body = read_note(target)
    assert "原有内容" in body
    assert "队列满时要限流" in body
    assert list_drafts(vault) == []


def test_fold_bumps_update_date(vault):
    target = vault / "计算机" /"队列串行化.md"
    write_note(target, {"类型": "概念", "更新": "2020-01-01"}, "# 队列串行化\n")

    _run(vault, FakeLLM(_plan_json(
        outcome="fold",
        target_path="计算机/队列串行化.md",
        content="补充内容\n",
    )))

    meta, _ = read_note(target)
    assert meta["更新"] == "2026-09-15"


def test_fold_inserts_before_the_related_section(vault):
    """`## 相关` 是收尾节，fold 追加的内容要排在它**前面**（Q101）。

    原先是 `body + 新内容`，直接怼在文件末尾——`## 相关` 就被挤到中间去了，
    后面还挂着新章节。实测两篇已经这样（`Windows 批处理文件必须用 GBK 编码`、
    `IE 缩放不是 100% 导致点击坐标算歪`）。
    """
    target = vault / "计算机" /"队列串行化.md"
    write_note(
        target,
        {"类型": "概念", "主题": ["计算机"]},
        "# 队列串行化\n\n原有内容\n\n## 相关\n\n- [[计算机]]\n",
    )

    _run(vault, FakeLLM(_plan_json(
        outcome="fold",
        target_path="计算机/队列串行化.md",
        content="## 补充：限流\n\n队列满时要限流\n",
    )))

    _, body = read_note(target)
    assert body.index("队列满时要限流") < body.index("## 相关")
    assert body.index("## 相关") < body.index("- [[计算机]]")
    assert body.index("原有内容") < body.index("队列满时要限流")


def test_fold_appends_at_the_end_when_there_is_no_related_section(vault):
    """没有 `## 相关` 就照旧追加到末尾——别为了插位置把笔记搅乱。"""
    target = vault / "计算机" /"队列串行化.md"
    write_note(target, {"类型": "概念"}, "# 队列串行化\n\n原有内容\n")

    _run(vault, FakeLLM(_plan_json(
        outcome="fold",
        target_path="计算机/队列串行化.md",
        content="补充内容\n",
    )))

    _, body = read_note(target)
    assert body.index("原有内容") < body.index("补充内容")


def test_pending_moves_draft_aside(vault):
    result, _ = _run(
        vault,
        FakeLLM(_plan_json(outcome="pending", pending_reason="无法判断主题")),
    )

    assert result.kind is ResultKind.PENDING
    assert "无法判断主题" in result.detail
    assert list_drafts(vault)[0].parent.name == PENDING
    assert not (vault / "计算机" /"并发写锁.md").exists()


# ---------- 失败路径（Q45：失败什么也不写）----------

def test_llm_error_leaves_everything_untouched(vault):
    class _Boom(LLM):
        def complete(self, system: str, user: str) -> str:
            raise LLMError("网络炸了")

    result, touched = _run(vault, _Boom())

    assert result.kind is ResultKind.FAILED
    assert "网络炸了" in result.error
    assert touched == []
    assert len(list_drafts(vault)) == 1          # 草稿原样留着，下次还能重试
    assert not (vault / "计算机" /"并发写锁.md").exists()


def test_invalid_plan_leaves_everything_untouched(vault):
    result, touched = _run(vault, FakeLLM(_plan_json(target_path="_附件/x.md")))

    assert result.kind is ResultKind.FAILED
    assert touched == []
    assert not (vault / ATTACHMENTS / "x.md").exists()


def test_orphan_plan_is_rejected_and_nothing_written(vault):
    result, _ = _run(vault, FakeLLM(_plan_json(content="# 没有链接\n")))
    assert result.kind is ResultKind.FAILED
    assert not (vault / "计算机" /"并发写锁.md").exists()


def test_bad_json_then_valid_json_succeeds(vault):
    """格式不合规时把错误喂回去重试——第二次成功。"""
    llm = FakeLLM(["这不是 JSON", _plan_json()])
    result, _ = _run(vault, llm)

    assert result.kind is ResultKind.CREATED
    assert len(llm.calls) == 2
    assert "不是合法 JSON" in llm.calls[1][1]     # 错误信息回喂进了第二次提示


def test_network_error_retries_without_hint(vault):
    """网络类失败不做提示回喂——模型没毛病，重试即可。"""
    class _Flaky(LLM):
        def __init__(self):
            self.calls = []

        def complete(self, system: str, user: str) -> str:
            self.calls.append((system, user))
            if len(self.calls) == 1:
                raise LLMError("超时")
            return _plan_json()

    llm = _Flaky()
    result, _ = _run(vault, llm)

    assert result.kind is ResultKind.CREATED
    assert len(llm.calls) == 2
    assert "上次尝试失败的原因" not in llm.calls[1][1]


def test_gives_up_after_max_attempts(vault):
    llm = FakeLLM("永远不是 JSON")
    result, _ = _run(vault, llm)
    assert result.kind is ResultKind.FAILED
    assert len(llm.calls) == organize.MAX_ATTEMPTS


def test_failure_reason_prevents_silent_loss(vault):
    """失败必须留下原因——不然用户不知道东西为什么卡在收件箱。"""
    result, _ = _run(vault, FakeLLM("坏输出"))
    assert result.error
    assert result.detail


# ---------- 事务回滚 ----------

def test_rollback_restores_vault_on_write_failure(vault, monkeypatch):
    """落盘中途失败 → 精确回滚，且不动用户未提交的改动。"""
    untouched = vault / "计算机" /"用户手写的.md"
    write_note(untouched, {"类型": "概念"}, "# 用户手写的\n")

    def _boom(*a, **kw):
        raise OSError("磁盘满了")

    monkeypatch.setattr(organize, "_write_note_safe", _boom)

    result, _ = _run(vault, FakeLLM(_plan_json()))

    assert result.kind is ResultKind.FAILED
    assert "磁盘满了" in result.error
    assert not (vault / "计算机" /"并发写锁.md").exists()
    assert untouched.read_text(encoding="utf-8").startswith("---")


def test_rollback_does_not_revert_user_changes(vault, monkeypatch):
    """Q45：禁用 `git checkout .`——那会连用户未提交的改动一起还原。"""
    user_file = vault / "计算机" /"用户手写的.md"
    write_note(user_file, {"类型": "概念"}, "# 原始\n")
    user_file.write_text("用户刚改的内容", encoding="utf-8")   # 未提交

    def _boom(*a, **kw):
        raise OSError("炸")

    monkeypatch.setattr(organize, "_write_note_safe", _boom)
    _run(vault, FakeLLM(_plan_json()))

    assert user_file.read_text(encoding="utf-8") == "用户刚改的内容"


def test_rollback_restores_fold_target(vault, monkeypatch):
    """fold 中途失败时，被改写的目标笔记要还原成原样。"""
    target = vault / "计算机" /"队列串行化.md"
    write_note(target, {"类型": "概念"}, "# 队列串行化\n\n原有内容\n")
    before = target.read_bytes()

    calls = {"n": 0}
    real = organize.write_note

    def _fail_second(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("写盘失败")
        return real(*a, **kw)

    monkeypatch.setattr(organize, "_write_note_safe", _fail_second)

    result, _ = _run(vault, FakeLLM(_plan_json(
        outcome="fold",
        target_path="计算机/队列串行化.md",
        content="补充内容\n",
    )))

    assert result.kind is ResultKind.FAILED
    assert target.read_bytes() == before


# ---------- 批量与隔离 ----------

def test_organize_all_isolates_failures(vault):
    """Q45：10 条里 1 条判不了，不该拖垮另外 9 条。"""
    write_draft(vault, Draft(id="20260915-0001", body="第一条", source=None,
                             project=None, created_at="2026-09-15 14:32"))
    write_draft(vault, Draft(id="20260915-0002", body="第二条", source=None,
                             project=None, created_at="2026-09-15 14:32"))

    llm = FakeLLM([_plan_json(), "坏输出"])      # 第一条好，第二条坏
    results = organize.organize_all(vault, llm, when=WHEN, sleep=NO_SLEEP, commit=False)

    kinds = [r.kind for r in results]
    assert ResultKind.CREATED in kinds
    assert ResultKind.FAILED in kinds
    assert len(list_drafts(vault)) == 1          # 失败的那条还留着


def test_organize_all_returns_empty_for_empty_inbox(vault):
    assert organize.organize_all(vault, FakeLLM(_plan_json()), commit=False) == []


# ---------- git ----------

def test_commit_message_lists_changes(vault):
    result, _ = organize.organize_draft(
        vault, write_draft(vault, DRAFT), FakeLLM(_plan_json()),
        when=WHEN, sleep=NO_SLEEP,
    )
    msg = organize.build_commit_message([result])
    assert "整理草稿 1 条" in msg
    assert "新建" in msg


def test_commit_message_mentions_pending_and_failed():
    msg = organize.build_commit_message([
        OrganizeResult("a", ResultKind.PENDING, "归不了"),
        OrganizeResult("b", ResultKind.FAILED, "炸了"),
    ])
    assert "待归类 1 条" in msg
    assert "失败 1 条" in msg


def test_commit_message_counts_only_successes(vault):
    msg = organize.build_commit_message([
        OrganizeResult("a", ResultKind.CREATED, "甲"),
        OrganizeResult("b", ResultKind.PENDING, "乙"),
    ])
    assert "整理草稿 1 条" in msg       # pending 不算「整理成功」


def test_commit_uses_service_author(vault):
    """Q46：服务用独立 author，便于分出「AI 写的」和「我写的」。"""
    path = write_draft(vault, DRAFT)
    result, touched = organize.organize_draft(
        vault, path, FakeLLM(_plan_json()), when=WHEN, sleep=NO_SLEEP
    )
    organize.commit_changes(vault, touched, [result], WHEN)

    out = _git(vault, "log", "-1", "--format=%an <%ae>")
    assert "kb-service" in out.stdout


def test_commit_message_survives_chinese(vault):
    """Windows 下 git 输出是 UTF-8 而 subprocess 默认按 GBK 解码——
    中文 commit message 会让读取线程抛 UnicodeDecodeError，主流程只看到
    stdout=None。这条测试钉住 utf-8 解码。"""
    path = write_draft(vault, DRAFT)
    result, touched = organize.organize_draft(
        vault, path, FakeLLM(_plan_json()), when=WHEN, sleep=NO_SLEEP
    )
    organize.commit_changes(vault, touched, [result], WHEN)

    out = _git(vault, "log", "-1", "--format=%s")
    assert out.returncode == 0
    assert out.stdout is not None
    assert "整理草稿" in out.stdout


def test_commit_only_stages_touched_files(vault):
    """Q46：禁用 `git add -A`，否则会把用户未提交的编辑裹进来。"""
    user_file = vault / "计算机" /"用户手写的.md"
    write_note(user_file, {"类型": "概念"}, "# 用户手写的\n")

    path = write_draft(vault, DRAFT)
    result, touched = organize.organize_draft(
        vault, path, FakeLLM(_plan_json()), when=WHEN, sleep=NO_SLEEP
    )
    organize.commit_changes(vault, touched, [result], WHEN)

    staged = _git(vault, "show", "--name-only", "--format=", "HEAD").stdout
    assert "用户手写的.md" not in staged
    assert "并发写锁.md" in staged


def test_commit_returns_false_when_nothing_touched(vault):
    assert organize.commit_changes(vault, [], [], WHEN) is False


def test_full_run_writes_journal_and_commits(vault):
    write_draft(vault, DRAFT)
    organize.organize_all(vault, FakeLLM(_plan_json()), when=WHEN, sleep=NO_SLEEP)

    journal = vault / INDEX / "整理日志" / "2026-09-15.md"
    assert journal.exists()
    assert "新建" in journal.read_text(encoding="utf-8")

    # 整轮只产生一个 commit
    count = _git(vault, "rev-list", "--count", "HEAD").stdout.strip()
    assert count == "2"                  # 骨架 1 + 本次整理 1


# ---------- 流程日志（Q89）----------

def test_organize_emits_flow_steps(vault, monkeypatch):
    """整理会把每一步说进流程日志（Q89）。"""
    rows = []
    monkeypatch.setattr("kb.core.flow.emit", lambda step, text: rows.append((step, text)))

    _run(vault, FakeLLM([_plan_json()]))

    steps = [s for s, _ in rows]
    assert "规划" in steps
    assert "校验" in steps
    assert "落盘" in steps


def test_flow_never_says_the_path_is_None(vault, monkeypatch):
    """pending 的计划没有 target_path——照原样打会印出「放进「None」」。

    2026-09-17 端到端跑出来的：工作日志页上明晃晃一行
    「模型决定放进「None」，类型是未定」，读的人只会一头雾水。
    """
    rows = []
    monkeypatch.setattr("kb.core.flow.emit", lambda step, text: rows.append((step, text)))

    _run(vault, FakeLLM(_plan_json(outcome="pending", pending_reason="说不清")))

    for _step, text in rows:
        assert "None" not in text, f"流程日志里印出了 None：{text}"
