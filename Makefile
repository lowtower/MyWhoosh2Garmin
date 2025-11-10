PROJECT = MyWhoosh2Garmin
SRC_CORE = myWhoosh2Garmin.py
# SRC_TEST = tests
SRC_TEST =
SRC_COMPLETE = $(SRC_CORE) $(SRC_TEST)
PYTHON=python3

help: ## Print help for each target
	$(info Makefile low-level Python API.)
	$(info =============================)
	$(info )
	$(info Available commands:)
	$(info )
	@grep '^[[:alnum:]_-]*:.* ##' $(MAKEFILE_LIST) \
		| sort | awk 'BEGIN {FS=":.* ## "}; {printf "%-25s %s\n", $$1, $$2};'

clean: ## Cleanup
	@rm -rf ./.env
	@rm -f  ./*.pyc
	@rm -rf ./__pycache__
	@rm -f  $(SRC_CORE)/*.pyc
	@rm -rf $(SRC_CORE)/__pycache__
	@rm -f  $(SRC_TEST)/*.pyc
	@rm -rf $(SRC_TEST)/__pycache__
	@rm -f  $(SRC_EXAMPLES)/*.pyc
	@rm -rf $(SRC_EXAMPLES)/__pycache__
	@rm -rf ./.coverage
	@rm -rf ./coverage.xml
	@rm -rf ./.pytest_cache
	@rm -rf ./.mypy_cache
	@rm -rf ./site
	@rm -rf ./reports

.PHONY: setup
setup: ## Setup virtual environment
	$(PYTHON) -m venv .env
	.env/bin/pip install --upgrade pip flit_core
	.env/bin/pip install --upgrade -r requirements.txt
	.env/bin/pip install --upgrade -r requirements-dev.txt

.PHONY: install
install: setup ## install package
	.env/bin/pip install .

.PHONY: format
format: ## Format the code
	.env/bin/isort \
		$(SRC_COMPLETE)
	.env/bin/python -m ruff format \
		$(SRC_COMPLETE)

.PHONY: lint
lint: ## Lint the code
	.env/bin/pycodestyle \
	--max-line-length=120 \
		$(SRC_COMPLETE)
	.env/bin/isort \
		$(SRC_COMPLETE) \
		--check --diff
	.env/bin/pyflakes \
		$(SRC_COMPLETE)
	.env/bin/pylint \
		$(SRC_COMPLETE)
	.env/bin/python -m ruff check \
		$(SRC_COMPLETE)
	.env/bin/mypy \
		$(SRC_COMPLETE)
	.env/bin/codespell \
	    README.md gpxtrackposter/*.py tests/*.py scripts/*.py

.PHONY: test
test: ## Test the code
	.env/bin/pytest tests

.PHONY: coverage
coverage: ## Generate coverage report for the code
	.env/bin/pytest --cov=gpxtrackposter --cov-branch --cov-report=term --cov-report=html tests

.PHONY: documentation
documentation: ## Generate documentation
	.env/bin/python -m mkdocs build --clean --verbose 
