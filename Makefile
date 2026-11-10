PY := .venv/bin/python

.PHONY: demo panel test test-all trial overnight watch report homeostatic homeostatic-test homeostatic-report

demo:
	$(PY) -m kokopelli.life.panel --demo

panel:
	$(PY) -m kokopelli.life.panel

trial:
	caffeinate -is $(PY) -u -m kokopelli.life.overnight --trial --hours 1

overnight:
	caffeinate -is $(PY) -u -m kokopelli.life.overnight --hours $(or $(HOURS),8)

watch:
	$(PY) -m kokopelli.life.panel --db out/overnight/latest/life.db --watch --port 8770

report:
	$(PY) -m kokopelli.life.report

test:
	@for file in kokopelli/life/static/*.js; do cp $$file /tmp/kokopelli-check.mjs && node --check /tmp/kokopelli-check.mjs || { echo "node --check failed: $$file"; exit 1; }; done
	@$(PY) -m unittest -q tests.life.test_life_store tests.life.test_life_windows tests.life.test_life_engine tests.life.test_life_panel tests.life.test_life_memory tests.life.test_life_architecture tests.life.test_life_pipeline tests.life.test_life_gpu_queue

homeostatic:
	caffeinate -is $(PY) -u -m experiments.homeostatic.experiment --seeds $(or $(SEEDS),0)

homeostatic-test:
	$(PY) -m unittest experiments.homeostatic.tests.test_homeostatic_world experiments.homeostatic.tests.test_homeostatic_benchmark tests.life.test_homeostatic_watch experiments.homeostatic.tests.test_homeostatic_export experiments.homeostatic.tests.test_homeostatic_grpo

homeostatic-report:
	$(PY) -m experiments.homeostatic.report

# Every suite, one line each. MAC=1 adds mac_server, VERBOSE=1 shows full output.
test-all:
	@bash tools/fable/test_all.sh
