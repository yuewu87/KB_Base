"""命令行接口（Q28）。

**CLI 是最通用的一层**——「能跑 shell」几乎是所有 agent harness 的底线能力，
比 MCP 的覆盖面广得多。

CLI 自己不碰文件：所有写入都走 HTTP 打到服务进程，服务没跑就自动拉起（Q29/Q39）。
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import httpx

from kb.api import runtime
from kb.config import Config, ConfigError, load_config

TIMEOUT = 600.0          # 整理要调 LLM，给足时间


def make_client(cfg: Config) -> httpx.Client:
    """建立到服务进程的连接。服务没跑就拉起来（Q39）。"""
    port = runtime.ensure_service(cfg)
    return httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=TIMEOUT)


def read_content(args) -> str:
    """正文来源优先级：`--content` > `--file` > stdin。"""
    if getattr(args, "content", None):
        return args.content
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def default_project() -> str | None:
    """Q30：默认取 **git 仓库根**的目录名，不是 cwd 的 basename。

    用 git 根是因为 agent 可能停在子目录（如 `src/kb/core/`），
    那样 basename 会取到 `core`，挂错项目。
    """
    from kb.core.vault import project_name_from_cwd

    return project_name_from_cwd(Path.cwd())


# ------------------------------------------------------------ 命令

def cmd_push(args) -> int:
    cfg = load_config()
    content = read_content(args).strip()
    if not content:
        print("正文为空。用 --content / --file 传入，或从 stdin 管道输入。", file=sys.stderr)
        return 2

    project = args.project if args.project is not None else default_project()

    with make_client(cfg) as client:
        resp = client.post(
            "/push",
            json={
                "content": content,
                "project": project,
                "source": args.source,
                "revise_target": args.revise,
            },
        )
        resp.raise_for_status()
        print(f"已收，id={resp.json()['id']}")
    return 0


def cmd_inbox(args) -> int:
    cfg = load_config()
    with make_client(cfg) as client:
        data = client.get("/inbox").raise_for_status().json()

    if not data["count"]:
        print("收件箱是空的。")
        return 0

    print(f"收件箱：{data['count']} 条待整理")
    for item in data["items"]:
        flags = []
        if item["pending"]:
            flags.append("待归类")
        if item["project"]:
            flags.append(item["project"])
        suffix = f"  [{'｜'.join(flags)}]" if flags else ""
        print(f"  {item['id']}  {item['preview']}{suffix}")
    return 0


def cmd_organize(args) -> int:
    cfg = load_config()
    with make_client(cfg) as client:
        resp = client.post("/organize", json={"draft_id": args.draft_id})
        if resp.status_code == 404:
            print(resp.json()["detail"], file=sys.stderr)
            return 1
        resp.raise_for_status()
        data = resp.json()

    if not data["count"]:
        print("没有待整理的草稿。")
        return 0

    # 报告：与工作日志同源（Q50）——同一批 results 的另一个出口
    print(f"整理完成，{data['count']} 条：")
    for r in data["results"]:
        line = f"  [{r['kind']}] {r['detail']}"
        if r["error"]:
            line += f" —— {r['error']}"
        print(line)

    failed = sum(1 for r in data["results"] if r["kind"] == "failed")
    return 1 if failed == data["count"] else 0


def cmd_search(args) -> int:
    cfg = load_config()
    with make_client(cfg) as client:
        resp = client.get("/search", params={"q": args.query})
        resp.raise_for_status()
        data = resp.json()

    if not data["count"]:
        print("没找到。")
        return 0
    print(f"找到 {data['count']} 条：")
    for item in data["items"]:
        tags = "、".join(item["tags"]) or "无"
        print(f"  {item['path']}")
        print(f"    {item['title']}｜标签：{tags}")
    return 0


def cmd_sweep(args) -> int:
    """手动跑一次巡检（调试用）。不受 6 天限制——服务那边会写回上次时间。"""
    cfg = load_config()
    with make_client(cfg) as client:
        resp = client.post("/sweep")
        resp.raise_for_status()
        data = resp.json()
    print(f"巡检完成：{data['summary']}")
    for m in data["tag_merges"]:
        print(f"  标签：{m['from']} → {m['to']}")
    for m in data["dir_merges"]:
        print(f"  目录：{m['from']} → {m['to']}")
    return 0


def cmd_status(args) -> int:
    cfg = load_config()
    port = runtime.running_port()
    if port is None:
        print("服务未在运行（下次调用会自动拉起）。")
    else:
        print(f"服务在运行：http://127.0.0.1:{port}")
        if runtime.is_stale():
            # 别用 ⚠️ 之类的符号：中文 Windows 的控制台与管道是 GBK，
            # 编不出来的字符会抛 UnicodeEncodeError。这里两个字就能说明白。
            print("警告：它比磁盘上的代码旧——仍在跑改动前的逻辑。")
            print("    跑 `kb stop` 停掉，下次调用会自动用当前代码拉起。")
    print(f"vault: {cfg.vault_path}")
    return 0


def cmd_web(args) -> int:
    """确保服务在跑，打印地址，并把网页打开。

    **给人用的入口**（`web.bat` 双击就是调它）。CLI 那边不该关心端口——
    `service.json` 自动发现就够；人要的是一个**能收藏、不用记**的地址。
    """
    cfg = load_config()
    port = runtime.ensure_service(cfg)
    url = f"http://127.0.0.1:{port}"
    print(f"知识库网页：{url}")
    if runtime.is_stale():
        print("警告：它比磁盘上的代码旧——仍在跑改动前的逻辑。")
        print("    跑 `kb stop` 停掉，下次调用会自动用当前代码拉起。")
    webbrowser.open(url)
    return 0


def cmd_stop(args) -> int:
    if runtime.stop_service():
        print("服务已停止。下次调用会自动用当前代码拉起。")
    else:
        print("服务本来就没在运行。")
    return 0


# ------------------------------------------------------------ 入口

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kb", description="KN_Base 知识库命令行")
    sub = parser.add_subparsers(dest="command", required=True)

    p_push = sub.add_parser("push", help="投递一条草稿到收件箱")
    p_push.add_argument("--content", help="正文")
    p_push.add_argument("--file", help="从文件读正文")
    p_push.add_argument("--project", help="项目名（默认取 git 根目录名）")
    p_push.add_argument("--source", help="来源：会话 / 书籍 / 网页 / 论文")
    p_push.add_argument("--revise", help="修改已有笔记：指定目标文件名（不含 .md）")
    p_push.set_defaults(func=cmd_push)

    p_org = sub.add_parser("organize", help="整理草稿（不填 id 则整理全部）")
    p_org.add_argument("draft_id", nargs="?", help="只整理这一条")
    p_org.set_defaults(func=cmd_organize)

    p_inbox = sub.add_parser("inbox", help="查看收件箱")
    p_inbox.set_defaults(func=cmd_inbox)

    p_search = sub.add_parser("search", help="检索笔记")
    p_search.add_argument("query", help="关键词")
    p_search.set_defaults(func=cmd_search)

    p_web = sub.add_parser("web", help="打开知识库网页（服务没跑就拉起来）")
    p_web.set_defaults(func=cmd_web)

    p_sweep = sub.add_parser("sweep", help="巡检一次：收拾全库的标签与目录")
    p_sweep.set_defaults(func=cmd_sweep)

    p_status = sub.add_parser("status", help="查看服务状态")
    p_status.set_defaults(func=cmd_status)

    p_stop = sub.add_parser("stop", help="停掉服务（改了代码之后用）")
    p_stop.set_defaults(func=cmd_stop)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except httpx.HTTPError as exc:
        print(f"与服务通信失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
