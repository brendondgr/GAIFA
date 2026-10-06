# Developer shortcuts. Day-to-day use is the `lcpp` command (see README.md).
.PHONY: install test dev idle-check smoke

install:          ## venv, lcpp command, at-boot service; retires the legacy setup
	scripts/install.sh

test:             ## unit + API + CLI tests (fake llama-server; no GPU, no systemd)
	uv run pytest -q

dev:              ## foreground daemon on :7790 running instances as child processes
	LCPP_STATE_DIR=$$(mktemp -d) uv run python -m lcpp.daemon --port 7790 --dev

idle-check:       ## startup time, RSS and idle CPU of a throwaway daemon
	utils/measure_idle.sh --spawn

smoke:            ## real llama-server under systemd: MiniCPM on :7071, then stop
	uv run python utils/smoke_supervisor.py minicpm 7071
