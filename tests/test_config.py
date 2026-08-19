from pathlib import Path

import pytest

from dc_harness.config import Config, load_config, resolve_api_key


def test_default_config_when_no_file(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.toml")
    assert isinstance(cfg, Config)
    assert cfg.llm.base_url == "https://chat.motiftech.io/openapi/v1"
    assert cfg.llm.model == "motif-12.7b-reasoning"
    assert cfg.llm.api_key_env == "MOTIF_API_KEY"
    assert cfg.collect.delay_min_seconds == 1.5


def test_toml_overrides_defaults(tmp_path: Path):
    f = tmp_path / "config.toml"
    f.write_text(
        '[llm]\nbase_url = "https://example.test/v1"\nmodel = "m1"\n'
        '[collect]\ndelay_min_seconds = 3.0\n'
    )
    cfg = load_config(f)
    assert cfg.llm.base_url == "https://example.test/v1"
    assert cfg.llm.model == "m1"
    assert cfg.collect.delay_min_seconds == 3.0
    assert cfg.llm.api_key_env == "MOTIF_API_KEY"  # 병합: 기본값 유지


def test_resolve_api_key_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOTIF_API_KEY", "test-key-not-real")
    assert resolve_api_key(load_config(None)) == "test-key-not-real"


def test_resolve_api_key_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MOTIF_API_KEY", raising=False)
    with pytest.raises(KeyError, match="MOTIF_API_KEY"):
        resolve_api_key(load_config(None))
