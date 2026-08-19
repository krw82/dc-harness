from __future__ import annotations

import json
import re

from ..net.guard import UnsafeUrlError, validate_http_url

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_RE = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


class LlmJsonError(ValueError):
    pass


def strip_think(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def extract_json(text: str) -> dict | list:
    cleaned = strip_think(text).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    match = _JSON_RE.search(cleaned)
    if not match:
        raise LlmJsonError("no json object found in response")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LlmJsonError(f"invalid json: {exc}") from exc


class LlmClient:
    def __init__(self, base_url: str, model: str, api_key: str,
                 temperature: float = 0.3, timeout: float = 60.0, inner=None):
        try:
            validate_http_url(base_url)
        except UnsafeUrlError as exc:
            raise ValueError(f"unsafe llm base_url: {base_url}") from exc
        self.model, self.temperature = model, temperature
        if inner is None:
            from openai import OpenAI
            inner = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.inner = inner

    def chat_json(self, system: str, user: str, max_retries: int = 2) -> dict | list:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        last_error: LlmJsonError | None = None
        for _attempt in range(max_retries + 1):
            response = self.inner.chat.completions.create(
                model=self.model, messages=messages, temperature=self.temperature,
                stream=False)
            content = response.choices[0].message.content or ""
            try:
                return extract_json(content)
            except LlmJsonError as exc:
                last_error = exc
                messages = messages[:2] + [
                    {"role": "assistant", "content": content[:2000]},
                    {"role": "user", "content":
                     "지금 응답은 유효한 JSON이 아니었다. 설명 없이 요청된 JSON 객체만 출력해라."},
                ]
        raise last_error  # type: ignore[misc]
