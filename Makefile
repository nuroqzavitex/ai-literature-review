.PHONY: run test lint format check clean bench bench-selftest bench-quick bench-researchqa \
	docker-reset-start docker-clean

run:
	bash -lc 'mkdir -p logs; set -o pipefail; ./.venv/bin/uvicorn src.main:app --reload --host 0.0.0.0 --port 8000 2>&1 | ./.venv/bin/python scripts/rotating_tee.py logs/backend.log --max-bytes 524288000'

test:
	pytest tests/ -v --cov=src --cov-fail-under=60

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

check: lint format test

# Kiểm chính bộ đo trước — offline, ~1 giây, không cần API hay DB.
# Số liệu từ một bộ đo chưa hiệu chuẩn còn nguy hiểm hơn không có số.
bench-selftest:
	python -m benchmarks selftest

# Chạy nhanh: 1 chủ đề thật + 1 kiểm soát âm, đủ để thấy hệ thống còn lành.
bench-quick: bench-selftest
	python -m benchmarks run --only pos_01,neg_01 --label quick

# Chạy đầy đủ, lặp 2 lần mỗi chủ đề để đo được cả độ ổn định đầu ra.
bench: bench-selftest
	python -m benchmarks run --repeat 2 --label full

# Lớp bên thứ ba: chấm theo rubric ResearchQA. PHẢI chạy trong container — cần
# client LLM của src/ và cần DNS mà host không phân giải được.
# 🚨 Điểm thu được KHÔNG so sánh được với mốc đã công bố của họ (khác giám khảo).
bench-researchqa: bench-selftest
	docker compose -f docker-compose.yml run --rm --no-deps -T \
	  -v $$(pwd)/benchmarks:/app/benchmarks worker \
	  python -m benchmarks researchqa --limit 20 --base-url http://backend:8000/api/v1

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +

# Destructive Docker reset: removes all Docker containers, images, volumes,
# networks and build cache, then rebuilds and starts the complete compose stack.
# Bind-mounted project data under ./data is intentionally preserved.
docker-reset-start:
	@set -eu; \
		echo "Stopping and removing this project's containers and volumes..."; \
	docker compose down --volumes --remove-orphans || true; \
		echo 'Removing all Docker containers, images, volumes and networks...'; \
		containers="$$(docker ps --all --quiet)"; \
		if [ -n "$$containers" ]; then docker rm --force $$containers; fi; \
		docker system prune --all --volumes --force; \
		echo 'Removing Docker build cache...'; \
		docker builder prune --all --force; \
		echo 'Building images from scratch...'; \
		docker compose build --no-cache; \
		echo 'Starting the application...'; \
		docker compose up --detach; \
	echo 'Application status:'; \
	docker compose ps

# Short alias for the destructive reset/start workflow.
docker-clean: docker-reset-start
