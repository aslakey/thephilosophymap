.PHONY: check lint test validate report install-dev

# The three gates CI runs. Run this before opening a PR.
check: lint test validate

lint:
	ruff check .

test:
	pytest

validate:
	python scripts/validate.py

# Category counts per dimension -- useful when deciding whether a new category
# is worth adding or an existing one should absorb it.
report:
	python scripts/validate.py --report

install-dev:
	pip install -r requirements-dev.txt
