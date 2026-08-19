from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LlmConfig:
    base_url: str = "https://chat.motiftech.io/openapi/v1"
    model: str = "motif-12.7b-reasoning"
    api_key_env: str = "MOTIF_API_KEY"
    temperature: float = 0.3
    # reasoning 모델은 큰 입력에 수 분이 걸릴 수 있다 (실측 2026-08: 12k글자 60초 초과)
    timeout: float = 300.0
    max_chunk_chars: int = 5000


@dataclass
class CollectConfig:
    delay_min_seconds: float = 1.5
    delay_jitter_seconds: float = 0.5
    max_retries: int = 3
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
    cookies_env: str = "DC_COOKIES"


@dataclass
class Config:
    llm: LlmConfig = field(default_factory=LlmConfig)
    collect: CollectConfig = field(default_factory=CollectConfig)
    privacy_salt: str = "dch-salt"


def load_config(path: Path | None = None) -> Config:
    cfg = Config()
    if path is None or not Path(path).exists():
        return cfg
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    for section, target in (("llm", cfg.llm), ("collect", cfg.collect)):
        for key, value in data.get(section, {}).items():
            if hasattr(target, key):
                setattr(target, key, value)
    cfg.privacy_salt = data.get("privacy_salt", cfg.privacy_salt)
    return cfg


def resolve_api_key(cfg: Config) -> str:
    env = cfg.llm.api_key_env
    try:
        return os.environ[env]
    except KeyError as exc:
        raise KeyError(f"API key not found: set {env} environment variable") from exc
