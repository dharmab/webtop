# Webtop

A script to repeatedly HTTP GET a URL and print statistics, response codes and errors.

[![Build Status](https://dharmab.visualstudio.com/webtop/_apis/build/status/dharmab.webtop?branchName=master)](https://dharmab.visualstudio.com/webtop/_build/latest?definitionId=1&branchName=master)

## Usage

`python3 webtop/__init__.py <URL>`, or `docker run -it dharmab/webtop <URL>`

> Note: The Docker image does not respond to Ctrl+C and should instead be signalled via `docker kill`

See `--help` for more options, including multithreading support
