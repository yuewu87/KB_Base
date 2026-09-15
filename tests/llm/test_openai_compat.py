import pytest

from kb.llm.base import LLMError
from kb.llm.providers.openai_compat import OpenAICompatLLM


class _Choice:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _StubClient:
    """替身客户端：不联网，只记录调用参数。"""

    def __init__(self, content=None, raises=None):
        self._content = content
        self._raises = raises
        self.calls = []

        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if outer._raises:
                    raise outer._raises
                return _Resp(outer._content)

        self.chat = type("C", (), {"completions": _Completions()})()


@pytest.fixture
def patched(monkeypatch):
    def _install(stub):
        monkeypatch.setattr(
            "kb.llm.providers.openai_compat.OpenAI",
            lambda **kwargs: stub,
        )
        return stub

    return _install


def test_returns_message_content(patched):
    patched(_StubClient(content="模型输出"))
    llm = OpenAICompatLLM(api_key="k", base_url="https://x/v1", model="m")
    assert llm.complete("sys", "user") == "模型输出"


def test_passes_system_and_user_messages(patched):
    stub = patched(_StubClient(content="ok"))
    llm = OpenAICompatLLM(api_key="k", base_url="https://x/v1", model="m")
    llm.complete("系统提示", "用户内容")

    kwargs = stub.calls[0]
    assert kwargs["model"] == "m"
    assert kwargs["messages"] == [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户内容"},
    ]


def test_forwards_credentials_to_client(monkeypatch):
    """base_url 与 api_key 必须真的传到 SDK——漏了会静默打到官方端点。"""
    seen = {}

    def _fake_openai(**kwargs):
        seen.update(kwargs)
        return _StubClient(content="x")

    monkeypatch.setattr("kb.llm.providers.openai_compat.OpenAI", _fake_openai)
    OpenAICompatLLM(api_key="secret", base_url="https://custom/v1", model="m")

    assert seen["api_key"] == "secret"
    assert seen["base_url"] == "https://custom/v1"


def test_wraps_provider_error_as_llm_error(patched):
    from openai import OpenAIError

    patched(_StubClient(raises=OpenAIError("limit")))
    llm = OpenAICompatLLM(api_key="k", base_url="https://x/v1", model="m")
    with pytest.raises(LLMError, match="limit"):
        llm.complete("s", "u")


def test_empty_content_raises_llm_error(patched):
    patched(_StubClient(content=None))
    llm = OpenAICompatLLM(api_key="k", base_url="https://x/v1", model="m")
    with pytest.raises(LLMError, match="空内容"):
        llm.complete("s", "u")


def test_empty_string_content_raises_llm_error(patched):
    """空字符串和 None 一样不可用——不能让空回复流到解析层。"""
    patched(_StubClient(content=""))
    llm = OpenAICompatLLM(api_key="k", base_url="https://x/v1", model="m")
    with pytest.raises(LLMError, match="空内容"):
        llm.complete("s", "u")
