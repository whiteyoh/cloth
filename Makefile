.PHONY: dev lint format test test-js check

dev:
	uvicorn main:app --reload

lint:
	ruff check .

format:
	ruff format .

test:
	pytest tests/ -v

test-js:
	npx jest --no-coverage

check: lint test
