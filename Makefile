.PHONY: test lint run
test:
	pytest tests/ -q
lint:
	ruff check app/ tests/
run:
	streamlit run app.py
