.PHONY: default install build lint type-check format format-check ci

CODE_DIR=webtop

default: ci

install:
	pip install -r requirements.txt
	pip install -r requirements.build.txt

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
