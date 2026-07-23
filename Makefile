# sage-birdnet2 -- Makefile
#
# `make test` runs the OFFLINE unit suite: the pure-stdlib v2 cache-consumer
# logic carried over byte-identical from sage-yolo2 (selection / seenstore) plus
# the audio-sidecar metadata reader contract test. Self-bootstraps a throwaway
# venv with pytest so the suite runs out-of-the-box on a clean checkout.
#
# The full inference test (real BirdNET V2.4 on real audio) is separate and
# CI/GPU-node-owned -- this offline suite touches no BirdNET, no model, no node.

VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: test clean

test: $(VENV)/.stamp
	$(PY) -m pytest -q tests/test_selection.py tests/test_seenstore.py tests/test_sidecar_meta.py

$(VENV)/.stamp:
	python3 -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet pytest
	touch $@

clean:
	rm -rf $(VENV)
