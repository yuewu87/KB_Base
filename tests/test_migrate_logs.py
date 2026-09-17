"""旧日志文件 → 按天目录。跑完即弃的一次性迁移。"""

import json

from scripts.migrate_logs import migrate_flow, migrate_runtime


def test_migrate_flow_moves_whole_file(tmp_path):
    """flow.jsonl 里全是同一天 → 整份搬过去。"""
    logs = tmp_path / "logs"
    logs.mkdir()
    rows = [
        {"at": "2026-09-17 10:00:00", "run": "r1", "step": "投递", "text": "a"},
        {"at": "2026-09-17 10:01:00", "run": "r1", "step": "规划", "text": "b"},
    ]
    (logs / "flow.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )

    migrate_flow(logs)

    assert not (logs / "flow.jsonl").exists()
    out = logs / "flow" / "2026-09-17.jsonl"
    assert out.is_file()
    got = [json.loads(x)["text"] for x in out.read_text(encoding="utf-8").splitlines()]
    assert got == ["a", "b"]


def test_migrate_flow_splits_across_days(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    rows = [
        {"at": "2026-09-16 23:59:00", "run": "r1", "step": "投递", "text": "昨天的"},
        {"at": "2026-09-17 00:01:00", "run": "r1", "step": "规划", "text": "今天的"},
    ]
    (logs / "flow.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )

    migrate_flow(logs)

    assert (logs / "flow" / "2026-09-16.jsonl").is_file()
    assert (logs / "flow" / "2026-09-17.jsonl").is_file()


def test_migrate_flow_noop_when_absent(tmp_path):
    """旧文件不在 → 什么都不做，不抛。"""
    migrate_flow(tmp_path)


def test_migrate_flow_skips_broken_lines(tmp_path):
    """坏行跳过，别让整份迁移挂掉。"""
    logs = tmp_path / "logs"
    logs.mkdir()
    good = {"at": "2026-09-17 10:00:00", "run": "r", "step": "投递", "text": "好的"}
    (logs / "flow.jsonl").write_text(
        json.dumps(good, ensure_ascii=False) + "\n" + '{"at": "2026-09-1\n',
        encoding="utf-8",
    )

    migrate_flow(logs)

    out = logs / "flow" / "2026-09-17.jsonl"
    assert [json.loads(x)["text"] for x in out.read_text(encoding="utf-8").splitlines()] == ["好的"]


def test_migrate_runtime_splits_by_line_timestamp(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "kb.log").write_text(
        "2026-09-16 23:59:59,000 INFO    kb.push: 昨天的\n"
        "2026-09-17 00:00:01,000 INFO    kb.push: 今天的\n"
        "没有时间戳的半行\n",
        encoding="utf-8",
    )

    migrate_runtime(logs)

    assert not (logs / "kb.log").exists()
    assert (logs / "kb" / "2026-09-16.log").read_text(encoding="utf-8").strip().endswith("昨天的")
    today = (logs / "kb" / "2026-09-17.log").read_text(encoding="utf-8")
    assert "今天的" in today
    assert "没有时间戳的半行" in today          # 认不出日期的归到**上一行所在的那天**


def test_migrate_runtime_noop_when_absent(tmp_path):
    migrate_runtime(tmp_path)
