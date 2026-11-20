.PHONY: test test-python test-js lint

test: test-python test-js

test-python:
	python3 -m unittest discover -s tests -v

test-js:
	node --test tests/validate.test.mjs

lint:
	python3 -m py_compile bridge/slack_chrome_bridge.py
	node --check extension/worker.js
	node --check extension/slack-api.js
	node --check extension/validate.js
