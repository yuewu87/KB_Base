"""库的生命周期：状态推断、路径体检、搬家、移除。"""

from kb.core.lifecycle import Busy


def test_acquire_succeeds_when_idle():
    busy = Busy()
    assert busy.what is None
    assert busy.acquire("organize") is True
    assert busy.what == "organize"


def test_acquire_fails_while_held():
    """**不等待，直接返回 False。** 排队等只会把一个「正在整理」变成
    一串排队请求，而调用方要的是「现在不行，等会儿再来」。"""
    busy = Busy()
    busy.acquire("organize")
    assert busy.acquire("migrate") is False
    assert busy.what == "organize"       # 先来的那个不被顶掉


def test_release_frees_it():
    busy = Busy()
    busy.acquire("organize")
    busy.release()
    assert busy.what is None
    assert busy.acquire("migrate") is True


def test_label_is_chinese():
    """409 的文案要给人看，不能写 `正在migrate`。"""
    busy = Busy()
    busy.acquire("migrate")
    assert busy.label == "迁移"
