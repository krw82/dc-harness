import pytest

from dc_harness.llm.client import LlmClient, LlmJsonError, extract_json, strip_think


def test_strip_think():
    assert strip_think('<think>reasoning...</think>{"a": 1}') == '{"a": 1}'
    assert strip_think("no tags") == "no tags"


def test_extract_json_from_codefence():
    assert extract_json('말씀드리면:\n```json\n{"topics": []}\n```\n끝') == {"topics": []}


def test_extract_json_invalid_raises():
    with pytest.raises(LlmJsonError):
        extract_json("json이 아님")


class _Msg:
    pass


class FakeCompletions:
    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.replies.pop(0)
        msg, choice = _Msg(), _Msg()
        msg.content = content
        choice.message = msg
        wrapper = _Msg()
        wrapper.choices = [choice]
        return wrapper


class FakeInner:
    def __init__(self, replies: list[str]):
        self.chat = type("M", (), {})
        self.chat.completions = FakeCompletions(replies)


def make_client(replies: list[str]) -> LlmClient:
    return LlmClient("https://93.184.216.34/v1", "m", "fake-key", inner=FakeInner(replies))


def test_chat_json_success_first_try():
    client = make_client(['```json\n{"ok": true}\n```'])
    assert client.chat_json("sys", "user") == {"ok": True}


def test_chat_json_retries_on_bad_json_then_repair():
    client = make_client(["이건 json 아님", '{"fixed": 1}'])
    assert client.chat_json("sys", "user", max_retries=1) == {"fixed": 1}
    assert "JSON" in client.inner.chat.completions.calls[-1]["messages"][-1]["content"]


def test_chat_json_gives_up_after_retries():
    client = make_client(["bad", "bad", "bad"])
    with pytest.raises(LlmJsonError):
        client.chat_json("sys", "user", max_retries=2)
