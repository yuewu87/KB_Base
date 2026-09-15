import pytest

from kb.llm.base import LLM, FakeLLM, LLMError


def test_llm_is_abstract():
    with pytest.raises(TypeError):
        LLM()


def test_fake_llm_records_calls_and_repeats_single_response():
    llm = FakeLLM("固定响应")
    assert llm.complete("sys", "u1") == "固定响应"
    assert llm.complete("sys", "u2") == "固定响应"
    assert len(llm.calls) == 2
    assert llm.calls[0] == ("sys", "u1")


def test_fake_llm_drains_queue_in_order():
    llm = FakeLLM(["第一次", "第二次"])
    assert llm.complete("s", "u") == "第一次"
    assert llm.complete("s", "u") == "第二次"


def test_fake_llm_string_never_exhausts():
    """传字符串 = 固定响应，重复调用永远返回它。"""
    llm = FakeLLM("固定响应")
    assert llm.complete("s", "u") == "固定响应"
    assert llm.complete("s", "u") == "固定响应"


def test_fake_llm_one_element_list_still_exhausts():
    """单元素**列表**是「队列长度 1」，不是「固定响应」——两者语义不同。

    曾经用「len(responses) == 1」来区分这两种模式，导致 `["a", "b"]` 在第 2 次
    调用后卡住不再消耗、永远不抛异常，「重试 N 次后放弃」的路径根本测不到。
    这条测试钉住正确的区分方式：只看构造时传入的是 str 还是 list。
    """
    llm = FakeLLM(["只有一条"])
    assert llm.complete("s", "u") == "只有一条"
    with pytest.raises(LLMError):
        llm.complete("s", "u")


def test_fake_llm_two_responses_then_exhausted():
    """多条响应耗尽后要抛，用来验证「重试 N 次后放弃」的路径。"""
    llm = FakeLLM(["a", "b"])
    llm.complete("s", "u")
    llm.complete("s", "u")
    with pytest.raises(LLMError):
        llm.complete("s", "u")


def test_fake_llm_empty_list_exhausted_immediately():
    llm = FakeLLM([])
    with pytest.raises(LLMError, match="队列已空"):
        llm.complete("s", "u")
