PY := .venv/bin/python

.PHONY: demo panel test test-all trial overnight watch report homeostatic homeostatic-test homeostatic-report

demo:
	$(PY) -m life.panel --demo

panel:
	$(PY) -m life.panel

trial:
	caffeinate -is $(PY) -u -m life.overnight --trial --hours 1

overnight:
	caffeinate -is $(PY) -u -m life.overnight --hours $(or $(HOURS),8)

watch:
	$(PY) -m life.panel --db out/overnight/latest/life.db --watch --port 8770

report:
	$(PY) -m life.report

test:
	for file in life/static/*.js; do cp $$file /tmp/kokopelli-check.mjs && node --check /tmp/kokopelli-check.mjs || exit 1; done
	$(PY) -m unittest tests.test_life_store tests.test_life_windows tests.test_life_engine tests.test_life_panel tests.test_life_memory

homeostatic:
	caffeinate -is $(PY) -u -m homeostatic.experiment --seeds $(or $(SEEDS),0)

homeostatic-test:
	$(PY) -m unittest tests.test_homeostatic_world tests.test_homeostatic_benchmark tests.test_homeostatic_watch tests.test_homeostatic_grpo

homeostatic-report:
	$(PY) -m homeostatic.report

test-all:
	$(PY) -m unittest discover -s tests -v
