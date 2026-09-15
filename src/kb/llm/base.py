"""LLM 抽象接口。

上层只依赖这个接口，不依赖具体供应商（Q33/Q54）。
测试时用 FakeLLM 替换真实实现，不跑真实 API（Q52）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    """LLM 调用失败：网络、超时、限流、返回为空等。"""


class LLM(ABC):
    """模型的最小接口——只要能把提示词变成文本就够。"""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """返回模型输出的纯文本。失败时抛 LLMError。"""


class FakeLLM(LLM):
    """测试用假实现。

    传字符串 → 每次都返回它（永不耗尽）；
    传列表   → 按顺序吐出，队列见底后再调用则抛 LLMError。

    后者用来验证「重试 N 次后放弃」这类路径——所以列表必须真的会耗尽。

    ⚠️ 别用「队列长度是否为 1」来区分这两种模式：那会让 `["a", "b"]`
    在第 2 次调用后卡住不再消耗，永远不抛异常，测试也就永远走不到放弃分支。
    必须记住**构造时**传入的是字符串还是列表。
    """

    def __init__(self, responses: str | list[str]):
        self._fixed: str | None = responses if isinstance(responses, str) else None
        self._queue: list[str] = [] if isinstance(responses, str) else list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self._fixed is not None:
            return self._fixed
        if not self._queue:
            raise LLMError("FakeLLM 的响应队列已空")
        return self._queue.pop(0)
