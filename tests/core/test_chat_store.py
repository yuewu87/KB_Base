"""会话存储。存服务侧，**不入库**——代码仓库是公开的。"""

from kb.core.chat_store import (
    append_message,
    chat_path,
    list_chats,
    load_chat,
    new_chat_id,
    save_chat,
)


def test_new_chat_id_shape():
    cid = new_chat_id()
    assert len(cid) == 13          # YYYYMMDD-xxxx
    assert cid[8] == "-"


def test_chat_path_under_chats_dir(tmp_path):
    assert chat_path(tmp_path, "20260917-a3f2").parent.name == "chats"


def test_save_then_load_roundtrip(tmp_path):
    cid = "20260917-a3f2"
    save_chat(tmp_path, cid, [{"role": "user", "content": "记一下 X"}])
    got = load_chat(tmp_path, cid)
    assert got["id"] == cid
    assert got["messages"][0]["content"] == "记一下 X"


def test_load_missing_chat_returns_none(tmp_path):
    assert load_chat(tmp_path, "不存在") is None


def test_append_message_keeps_order(tmp_path):
    cid = new_chat_id()
    append_message(tmp_path, cid, "user", "第一句")
    append_message(tmp_path, cid, "assistant", "第二句")
    chat = load_chat(tmp_path, cid)
    assert [m["content"] for m in chat["messages"]] == ["第一句", "第二句"]
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]


def test_list_chats_newest_first(tmp_path):
    append_message(tmp_path, "20260916-aaaa", "user", "旧")
    append_message(tmp_path, "20260917-bbbb", "user", "新")
    assert [c["id"] for c in list_chats(tmp_path)] == ["20260917-bbbb", "20260916-aaaa"]


def test_list_chats_empty_when_absent(tmp_path):
    assert list_chats(tmp_path) == []


def test_title_comes_from_first_user_message(tmp_path):
    cid = new_chat_id()
    append_message(tmp_path, cid, "user", "窗口缩放那个坑")
    assert load_chat(tmp_path, cid)["title"] == "窗口缩放那个坑"


def test_rejects_root_outside_data(tmp_path):
    """传 PROJECT_ROOT 会落到仓库根，而那条路径没被 gitignore 覆盖。

    这是**运行时**防线——测试只在跑的时候守着，而调用方可能在任何时候传错。
    """
    import pytest

    from kb.config import PROJECT_ROOT
    from kb.core.chat_store import chats_dir

    with pytest.raises(ValueError, match="不要传 PROJECT_ROOT"):
        chats_dir(PROJECT_ROOT)


def test_allows_tmp_path(tmp_path):
    """临时目录不在仓库里，随便传。"""
    from kb.core.chat_store import chats_dir

    assert chats_dir(tmp_path) == tmp_path / "chats"


def test_allows_data_dir():
    """正确用法：传 config.DATA_DIR。"""
    from kb.config import DATA_DIR
    from kb.core.chat_store import chats_dir

    assert chats_dir(DATA_DIR) == DATA_DIR / "chats"
