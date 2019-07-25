.PHONY: install build lint type-check format format-check

CODE_DIR=webtop

install:
	pip install -r requirements.txt

build:
	docker build -t webtop:latest .

LINTER=flake8
# E501 = line too long
LINTER_ARGS=--ignore E501 $(CODE_DIR)

lint:
	$(LINTER) $(LINTER_ARGS)

TYPE_CHECKER=mypy
TYPE_CHECKER_ARGS=$(CODE_DIR)

type-check:
	$(TYPE_CHECKER) $(TYPE_CHECKER_ARGS)

FORMATTER=black
FORMATTER_ARGS= --line-length 120 $(CODE_DIR)

format:
	$(FORMATTER) $(FORMATTER_ARGS)

format-check:
	$(FORMATTER) --check $(FORMATTER_ARGS)

ci: lint type-check format-check
