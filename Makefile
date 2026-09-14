install:
	pip install .[dev]

lint:
	ruff check .

typecheck:
	mypy src

test:
	pytest -q

security:
	bandit -r src

docker-build:
	docker build -t local_monitoring:dev .

docker-run:
	docker compose up
