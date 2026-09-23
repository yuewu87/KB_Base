import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from kb.api import cli
from kb.config import Config, ConfigError
from kb.core.vault import list_drafts, read_draft
from kb.llm.base import FakeLLM


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


class _Args:
    def __init__(self, **kw):
        self.content = kw.get("content")
        self.file = kw.get("file")
        self.project = kw.get("project")
        self.source = kw.get("source")
        self.draft_id = kw.get("draft_id")


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    (tmp_path / "计算机").mkdir(parents=True)
    return Config("k", "u", "m", tmp_path, None)


@pytest.fixture
def fake_server(monkeypatch, cfg, tmp_path):
    """把 CLI 的 HTTP 请求接到内存里的假服务上，不真起进程。

    用 starlette 的 `TestClient` 而不是 `httpx.ASGITransport`——后者不支持
    `with client as c` 的上下文管理器协议，而 CLI 正是那么用的。
    TestClient 本身就是 httpx.Client 子类。

    **`data_dir` 必须传**：`create_app` 的默认值是真实 `DATA_DIR`，不传的话
    流程日志会写进真库（`data/logs/flow/`）——测试跑一遍，真日志就涨一截。
    """
    from fastapi.testclient import TestClient

    from kb.api.http import create_app

    app = create_app(cfg, llm=FakeLLM(_plan_json()), data_dir=tmp_path)

    def _make_client(_cfg):
        return TestClient(app)

    monkeypatch.setattr(cli, "make_client", _make_client)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    return cfg


def test_web_opens_the_browser(fake_server, monkeypatch, capsys):
    """`kb web` = 确保服务在跑 → 打印地址 → 开浏览器。"""
    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    monkeypatch.setattr(cli.runtime, "ensure_service", lambda _cfg: 51823)
    monkeypatch.setattr(cli.runtime, "is_stale", lambda: False)

    assert cli.cmd_web(_Args()) == 0

    assert opened == ["http://127.0.0.1:51823"]
    assert "51823" in capsys.readouterr().out


def test_web_warns_when_the_service_is_stale(fake_server, monkeypatch, capsys):
    """服务跑着旧代码时要说一声——不然改了代码看不出效果，能白排查半天。"""
    monkeypatch.setattr(cli.webbrowser, "open", lambda _url: None)
    monkeypatch.setattr(cli.runtime, "ensure_service", lambda _cfg: 51823)
    monkeypatch.setattr(cli.runtime, "is_stale", lambda: True)

    cli.cmd_web(_Args())

    assert "比磁盘上的代码旧" in capsys.readouterr().out


# ---------- 纯函数 ----------

def test_read_content_prefers_flag(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.read_content(_Args(content="直接给的")) == "直接给的"


def test_read_content_from_file(tmp_path):
    f = tmp_path / "content.txt"
    f.write_text("文件里的内容", encoding="utf-8")
    assert cli.read_content(_Args(file=str(f))) == "文件里的内容"


def test_read_content_from_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("管道过来的内容"))
    assert cli.read_content(_Args()) == "管道过来的内容"


def test_read_content_empty_when_nothing(monkeypatch):
    monkeypatch.setattr(sys, "stdin", type("T", (), {"isatty": lambda self: True})())
    assert cli.read_content(_Args()) == ""


# ---------- 项目名默认值（Q30）----------

def test_default_project_uses_git_root(tmp_path, monkeypatch):
    """取 git 根的目录名，避免 agent 停在子目录时取到 core。"""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True)
    deep = tmp_path / "src" / "kb" / "core"
    deep.mkdir(parents=True)

    from kb.core.vault import project_name_from_cwd

    assert project_name_from_cwd(deep) == tmp_path.name


def test_default_project_is_none_outside_a_repo(tmp_path):
    """**非 git 仓库不再拿目录名顶替——返回 `None`。**

    原先回退到 `cwd.name`，于是从临时目录里投递会把项目记成 `Temp`：
    投递成功、不报错、不提示，直到哪天在库里看见一篇项目叫 `Temp` 的笔记
    才发现——正是这个项目一贯要消灭的「看起来一切正常」。

    项目自己的规矩是「静默回退可以，但**得让人一看就知道不对**」
    （`_log_level` 那条：坏配置用默认值跑着，设置窗里会显示默认值）。
    而项目名印在 frontmatter 里，没人会去看——**「看得见」这个前提不成立**，
    所以这里改成不猜。
    """
    from kb.core.vault import project_name_from_cwd

    assert project_name_from_cwd(tmp_path) is None


def test_push_outside_a_repo_is_rejected(fake_server, monkeypatch, tmp_path, capsys):
    """**取不到项目名就停下，不猜。**

    判据是「不在任何 git 仓库里」——这一条**机械可判**；而「`Temp` 是不是
    真项目名」判不了。所以能机械判的那条当闸，判不了的那条不该由代码猜。
    """
    monkeypatch.chdir(tmp_path)          # tmp_path 不是 git 仓库

    assert cli.main(["push", "--content", "内容"]) != 0

    err = capsys.readouterr().err
    assert "--project" in err                        # 说清两条出路
    assert "cd" in err
    assert not list_drafts(fake_server.vault_path)   # **一条都没写进去**


def test_push_accepts_an_explicitly_empty_project(fake_server, capsys):
    """`--project ""` ＝**明确不挂项目**，不是「没给」。

    网页投递本来就是项目留空（`/new` 那条），所以这是个**合法状态**——
    非仓库时报错挡的是「猜」，不是「不挂」。
    """
    assert cli.main(["push", "--content", "内容", "--project", ""]) == 0

    drafts = list_drafts(fake_server.vault_path)
    assert not read_draft(drafts[0]).project


def test_push_reports_the_project_it_used(fake_server, capsys):
    """投递成功要把**项目名印出来**——记错了当场看得见。

    原先只印一句 `已收，id=...`，项目名藏在 frontmatter 里，得 `kb inbox`
    才看得到（`[KN_Base]` 那个方括号）。而这正是这次那句「回退到目录名」
    能一路静默下去的原因：**没有任何一步把它显示给人看**。
    """
    assert cli.main(["push", "--content", "内容", "--project", "电商后台"]) == 0

    assert "电商后台" in capsys.readouterr().out


# ---------- 端到端（假服务）----------

def test_push_then_inbox_then_organize(fake_server, capsys):
    assert cli.main(["push", "--content", "并发写入会锁表", "--project", "电商后台"]) == 0
    assert "已收，id=" in capsys.readouterr().out

    assert cli.main(["inbox"]) == 0
    assert "并发写入会锁表" in capsys.readouterr().out

    assert cli.main(["organize"]) == 0
    assert "[created]" in capsys.readouterr().out

    assert (fake_server.vault_path / "计算机" / "并发写锁.md").exists()


def test_push_defaults_project_from_the_git_root(fake_server, monkeypatch, tmp_path):
    """在 git 仓库里不传 `--project` 时，仍然**取仓库根的目录名**。

    停在子目录也要取到根——那样 basename 会取成 `src`。
    """
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True)
    deep = tmp_path / "src"
    deep.mkdir()
    monkeypatch.chdir(deep)

    cli.main(["push", "--content", "内容"])

    drafts = list_drafts(fake_server.vault_path)
    assert read_draft(drafts[0]).project == tmp_path.name


def test_push_rejects_empty(fake_server, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert cli.main(["push"]) == 2
    assert "正文为空" in capsys.readouterr().err


def test_inbox_empty_message(fake_server, capsys):
    assert cli.main(["inbox"]) == 0
    assert "收件箱是空的" in capsys.readouterr().out


def test_organize_reports_nothing_to_do(fake_server, capsys):
    assert cli.main(["organize"]) == 0
    assert "没有待整理的草稿" in capsys.readouterr().out


def test_organize_single_id(fake_server, capsys):
    cli.main(["push", "--content", "第一条"])
    cli.main(["push", "--content", "第二条"])
    capsys.readouterr()

    first = sorted(p.stem for p in list_drafts(fake_server.vault_path))[0]
    assert cli.main(["organize", first]) == 0
    assert "整理完成，1 条" in capsys.readouterr().out
    assert len(list_drafts(fake_server.vault_path)) == 1      # 第二条还在


def test_status_when_service_down(fake_server, monkeypatch, capsys):
    monkeypatch.setattr(cli.runtime, "running_port", lambda: None)
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "服务未在运行" in out
    assert "vault:" in out


def test_status_when_service_up(fake_server, monkeypatch, capsys):
    monkeypatch.setattr(cli.runtime, "running_port", lambda: 51723)
    cli.main(["status"])
    assert "51723" in capsys.readouterr().out


def test_status_warns_when_service_is_stale(fake_server, monkeypatch, capsys):
    """改了代码但服务还跑着旧的——必须明确告警，否则改动看起来没生效。"""
    monkeypatch.setattr(cli.runtime, "running_port", lambda: 51723)
    monkeypatch.setattr(cli.runtime, "is_stale", lambda: True)

    cli.main(["status"])
    out = capsys.readouterr().out
    assert "比磁盘上的代码旧" in out
    assert "kb stop" in out


def test_stop_reports_when_nothing_running(fake_server, monkeypatch, capsys):
    monkeypatch.setattr(cli.runtime, "stop_service", lambda: False)
    assert cli.main(["stop"]) == 0
    assert "本来就没在运行" in capsys.readouterr().out


def test_stop_reports_success(fake_server, monkeypatch, capsys):
    monkeypatch.setattr(cli.runtime, "stop_service", lambda: True)
    assert cli.main(["stop"]) == 0
    assert "已停止" in capsys.readouterr().out


def test_config_error_exits_two(monkeypatch, capsys):
    def _boom():
        raise ConfigError("缺少必填配置 KB_LLM_API_KEY")

    monkeypatch.setattr(cli, "load_config", _boom)
    assert cli.main(["inbox"]) == 2
    assert "配置错误" in capsys.readouterr().err


def test_no_args_exits_with_usage():
    """不给子命令应该报用法错误，而不是静默退出。"""
    with pytest.raises(SystemExit):
        cli.main([])


# ---------- 删草稿（Q99）----------

def _draft(vault, draft_id: str, body: str = "写错了\n") -> None:
    from kb.core.models import Draft
    from kb.core.vault import write_draft

    write_draft(vault, Draft(
        id=draft_id, body=body, source="会话", project=None, created_at="2026-01-01 00:00",
    ))


def test_drop_deletes_and_reports(fake_server, capsys):
    """投错的东西得能撤——这是收件箱唯一的退路。"""
    _draft(fake_server.vault_path, "20260101-aaaa")

    code = cli.main(["drop", "20260101-aaaa"])

    assert code == 0
    assert "20260101-aaaa" in capsys.readouterr().out
    assert list_drafts(fake_server.vault_path) == []


def test_drop_takes_several_ids_at_once(fake_server, capsys):
    _draft(fake_server.vault_path, "20260101-aaaa")
    _draft(fake_server.vault_path, "20260101-bbbb")

    code = cli.main(["drop", "20260101-aaaa", "20260101-bbbb"])

    assert code == 0
    assert list_drafts(fake_server.vault_path) == []


def test_search_prints_the_body(fake_server, capsys):
    """`kb search` 的输出是会话层唯一的检索入口——正文不在里面，
    它就只能转头跟用户说「我拿不到具体条目」（Q103）。
    """
    from kb.core.vault import write_note

    write_note(
        fake_server.vault_path / "计算机" / "并发写锁.md",
        {"类型": "概念", "主题": ["计算机"]},
        "# 并发写锁\n\n并发写入会锁表。",
    )

    code = cli.main(["search", "锁表"])

    out = capsys.readouterr().out
    assert code == 0
    assert "并发写锁" in out
    assert "并发写入会锁表。" in out


def test_search_says_so_when_nothing_matches(fake_server, capsys):
    code = cli.main(["search", "查无此物"])
    assert code == 0
    assert "没找到" in capsys.readouterr().out


def test_drop_missing_id_reports_to_stderr_and_exits_one(fake_server, capsys):
    """删不掉的要说清楚是「没这条」，别假装删成功了。"""
    code = cli.main(["drop", "20260101-dead"])

    captured = capsys.readouterr()
    assert code == 1
    assert "20260101-dead" in captured.err


def test_drop_needs_at_least_one_id():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["drop"])
