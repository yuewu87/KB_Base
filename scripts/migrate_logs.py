"""把旧的单文件日志拆进按天目录。**跑完即弃的一次性脚本。**

旧格式（`logs/flow.jsonl`、`logs/kb.log`）只会出现这一次，所以不留常驻逻辑。

用法：

    python scripts/migrate_logs.py            # 默认 data/logs
    python scripts/migrate_logs.py <目录>

迁完会打印每个文件落到了哪。想先看一眼再动：

    python scripts/migrate_logs.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_DAY_FMT = "%Y-%m-%d"
# 运行日志行首形如 `2026-09-17 10:00:00,123`
_STAMP_LEN = 10


def migrate_flow(logs: Path, dry_run: bool = False) -> dict[str, int]:
    """`flow.jsonl` → `flow/YYYY-MM-DD.jsonl`（按记录里的 `at` 分）。

    返回 `{日期: 条数}`。
    """
    old = logs / "flow.jsonl"
    if not old.is_file():
        return {}

    buckets: dict[str, list[str]] = {}
    for line in old.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            day = str(row["at"])[:_STAMP_LEN]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue          # 坏行走掉，别让整份迁移挂掉
        buckets.setdefault(day, []).append(line)

    out_dir = logs / "flow"
    for day, lines in buckets.items():
        target = out_dir / f"{day}.jsonl"
        print(f"  flow: {len(lines):>5} 条 → {target}")
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")

    if not dry_run:
        old.unlink()
    return {day: len(lines) for day, lines in buckets.items()}


def migrate_runtime(logs: Path, dry_run: bool = False) -> dict[str, int]:
    """`kb.log` → `kb/YYYY-MM-DD.log`（按**行首时间戳**分）。

    **认不出日期的行归到「上一行所在的那天」**——运行日志是多行一条的
    （traceback 的后续行就没有时间戳），按行独立判断会把它们拆散。
    """
    old = logs / "kb.log"
    if not old.is_file():
        return {}

    buckets: dict[str, list[str]] = {}
    current: str | None = None
    for line in old.read_text(encoding="utf-8", errors="replace").splitlines():
        stamp = line[:_STAMP_LEN]
        if len(stamp) == _STAMP_LEN and stamp[4] == "-" and stamp[7] == "-":
            current = stamp
        if current is not None:
            buckets.setdefault(current, []).append(line)
        # 第一行就没有时间戳 → 没有可以归的日子，丢掉（它是残缺的）

    out_dir = logs / "kb"
    for day, lines in buckets.items():
        target = out_dir / f"{day}.log"
        print(f"  kb:   {len(lines):>5} 行 → {target}")
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")

    if not dry_run:
        old.unlink()
    return {day: len(lines) for day, lines in buckets.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="拆分旧的单文件日志")
    parser.add_argument("logs", nargs="?", default=None, help="日志目录，默认 data/logs")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不动文件")
    args = parser.parse_args()

    if args.logs:
        logs = Path(args.logs)
    else:
        from kb.config import PROJECT_ROOT
        logs = PROJECT_ROOT / "data" / "logs"

    if not logs.is_dir():
        print(f"目录不存在：{logs}")
        return

    print(f"在 {logs} 里找旧文件：")
    flow = migrate_flow(logs, args.dry_run)
    runtime = migrate_runtime(logs, args.dry_run)
    if not flow and not runtime:
        print("  没找到 flow.jsonl 或 kb.log —— 可能已经迁过了。")
    elif args.dry_run:
        print("（dry-run：什么都没动）")


if __name__ == "__main__":
    main()
