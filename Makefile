.PHONY: test lint smoke
test:
	.venv/bin/pytest -v
lint:
	.venv/bin/ruff check dc_harness tests
smoke:  # 실제 API 키 필요. 소규모 라이브 검증
	MOTIF_API_KEY=$${MOTIF_API_KEY:?set MOTIF_API_KEY} .venv/bin/dch run --gallery $${GALLERY:-crypto} --days 3 --pages 1
