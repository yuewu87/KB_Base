"""OpenAI 兼容端点实现（Q54）。

用 openai SDK 指向供应商的兼容端点。将来换供应商只改 base_url 和模型名，
本文件不用动。
"""

from __future__ import annotations

from openai import OpenAI, OpenAIError

from kb.llm.base import LLM, LLMError


class OpenAICompatLLM(LLM):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
    ) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._model = model

    def complete(self, system: str, user: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except OpenAIError as exc:
            # 统一成 LLMError，上层才不用认识具体供应商的异常类型（Q33）
            raise LLMError(str(exc)) from exc

        content = resp.choices[0].message.content
        if not content:
            raise LLMError("模型返回了空内容")
        return content
