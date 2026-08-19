from __future__ import annotations

import hashlib
import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    text = _TAG_RE.sub(" ", html.unescape(raw or ""))
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return _WS_RE.sub(" ", text).strip()


def author_hash(nick: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}\x00{nick}".encode("utf-8")).hexdigest()[:12]


def normalize_label(s: str) -> str:
    return re.sub(r"[\s\u200b]+", "", (s or "")).casefold()
