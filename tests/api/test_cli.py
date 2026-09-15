import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from kb.api import cli
from kb.config import Config, ConfigError
from kb.core.vault import KNOWLEDGE, list_drafts, read_draft
from kb.llm.base import FakeLLM


def _plan_json(**overrides) -> str:
    data = {
        "outcome": "create",
        "target_path": f"{KNOWLEDGE}/后端/并发写锁.md",
        "frontmatter": {"类型": "概念", "主题": ["后端"]},
        "content": "# 并发写锁\n\n见 [[后端]]\n",
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
    (tmp_path / KNOWLEDGE / "后端").mkdir(parents=True)
    return Config("k", "u", "m", tmp_path, None)


@pytest.fixture
def fake_server(monkeypatch, cfg):
    """把 CLI 的 HTTP 请求接到内存里的假服务上，不真起进程。

    用 starlette 的 `TestClient` 而不是 `httpx.ASGITransport`——后者不支持
    `with client as c` 的上下文管理器协议，而 CLI 正是那么用的。
    TestClient 本身就是 httpx.Client 子类。
    """
    from fastapi.testclient import TestClient

    from kb.api.http import create_app

    app = create_app(cfg, llm=FakeLLM(_plan_json()))

    def _make_client(_cfg):
        return TestClient(app)

    monkeypatch.setattr(cli, "make_client", _make_client)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    return cfg


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


def test_default_project_falls_back_to_cwd(tmp_path):
    """非 git 仓库回退到 cwd 的 basename，而不是返回 None。"""
    from kb.core.vault import project_name_from_cwd

    assert project_name_from_cwd(tmp_path) == tmp_path.name


# ---------- 端到端（假服务）----------

def test_push_then_inbox_then_organize(fake_server, capsys):
    assert cli.main(["push", "--content", "并发写入会锁表", "--project", "电商后台"]) == 0
    assert "已收，id=" in capsys.readouterr().out

    assert cli.main(["inbox"]) == 0
    assert "并发写入会锁表" in capsys.readouterr().out

    assert cli.main(["organize"]) == 0
    assert "[created]" in capsys.readouterr().out

    assert (fake_server.vault_path / KNOWLEDGE / "后端" / "并发写锁.md").exists()


def test_push_defaults_project_from_cwd(fake_server, monkeypatch, tmp_path):
    """不传 --project 时用当前目录推断，而不是留空。"""
    monkeypatch.chdir(tmp_path)
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
