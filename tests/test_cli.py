import json
from datetime import date
from pathlib import Path

from dc_harness.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ingest.jsonl"
TODAY = date.today()


class StubLlm:
    def __init__(self, cfg):
        pass

    def chat_json(self, system, user, max_retries=2):
        # map 단계 계약: 각 kind 키 아래 리스트
        return {"topics": [{"label": "전망", "post_nos": [101],
                            "keywords": ["매수"], "snippet": "s"}],
                "issues": [], "resonant": [],
                "entities": [],
                "voices": []}


def _shift_fixture_dates(tmp_path: Path) -> Path:
    posts = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        d["created_at"] = f"{TODAY.isoformat()}T09:00:00"
        posts.append(json.dumps(d, ensure_ascii=False))
    f = tmp_path / "today.jsonl"
    f.write_text("\n".join(posts) + "\n", encoding="utf-8")
    return f


def test_end_to_end_ingest_analyze_report(tmp_path: Path):
    db = tmp_path / "dch.db"
    fixture = _shift_fixture_dates(tmp_path)
    assert main(["ingest", "--gallery", "crypto", "--file", str(fixture),
                 "--db", str(db)]) == 0
    rc = main(["analyze", "--gallery", "crypto", "--days", "7", "--db", str(db),
               "--kinds", "topics"], llm_factory=StubLlm)
    assert rc == 0
    rc = main(["report", "--gallery", "crypto", "--days", "7",
               "--out", str(tmp_path / "reports"), "--db", str(db)], llm_factory=StubLlm)
    assert rc == 0
    reports = list((tmp_path / "reports" / "crypto").glob("*.md"))
    assert reports and "전망" in reports[0].read_text(encoding="utf-8")


def test_run_pipeline_with_file(tmp_path: Path):
    fixture = _shift_fixture_dates(tmp_path)
    db = tmp_path / "dch.db"
    rc = main(["run", "--gallery", "crypto", "--days", "7",
               "--db", str(db), "--file", str(fixture),
               "--out", str(tmp_path / "reports")], llm_factory=StubLlm)
    assert rc == 0
    assert list((tmp_path / "reports" / "crypto").glob("*.md"))


def test_report_without_analysis_fails(tmp_path: Path):
    rc = main(["report", "--gallery", "crypto", "--days", "7",
               "--out", str(tmp_path / "reports"), "--db", str(tmp_path / "dch.db")],
              llm_factory=StubLlm)
    assert rc == 1


def test_collect_missing_pages_ok(tmp_path: Path):
    # collect는 실네트워크를 쓰므로 CI에서는 페이지 0으로 스킵만 확인
    assert main(["collect", "--gallery", "crypto", "--pages", "0",
                 "--db", str(tmp_path / "dch.db")]) == 0


class FailingLlm:
    model = "stub"

    def __init__(self, cfg):
        pass

    def chat_json(self, system, user, max_retries=2):
        raise ValueError("invalid api key")


def test_analyze_all_chunks_failed_exits_nonzero(tmp_path: Path, capsys):
    fixture = _shift_fixture_dates(tmp_path)
    db = tmp_path / "dch.db"
    main(["ingest", "--gallery", "crypto", "--file", str(fixture), "--db", str(db)])
    rc = main(["analyze", "--gallery", "crypto", "--days", "7", "--db", str(db),
               "--kinds", "topics"], llm_factory=FailingLlm)
    assert rc == 1
    assert "모든 LLM 청크가 실패" in capsys.readouterr().err
