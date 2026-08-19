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


def test_extract_json_skips_reasoning_example_objects():
    # reasoning 모델 실측: 평문 추론 + 예시(JSON 아님) + 최종 답
    text = ('Okay, let me compute. The format is {"sum": <number>} so I need '
            'the value of 1+1. The answer: {"sum": 2}')
    assert extract_json(text) == {"sum": 2}


def test_extract_json_takes_first_valid_of_duplicates():
    text = '{"a": 1} {"a": 2}'
    assert extract_json(text) == {"a": 1}


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


class StreamEvent:
    def __init__(self, text: str):
        delta, choice = _Msg(), _Msg()
        delta.content = text
        choice.delta = delta
        self.choices = [choice]


class FakeStreamCompletions:
    def __init__(self, replies: list[list[str]]):
        self.replies = list(replies)

    def create(self, **kwargs):
        events = [StreamEvent(t) for t in self.replies.pop(0)]
        return iter(events)


def make_stream_client(chunks: list[str]) -> LlmClient:
    inner = type("M", (), {})
    inner.chat = type("M", (), {})
    inner.chat.completions = FakeStreamCompletions([chunks])
    return LlmClient("https://93.184.216.34/v1", "m", "fake-key", inner=inner)


def test_chat_json_collects_streaming_events():
    client = make_stream_client(['{"ok"', ": ", "true}"])
    assert client.chat_json("sys", "user") == {"ok": True}


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
