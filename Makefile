.PHONY: llama-render llama-command llama-run llama-install-user llama-start llama-stop llama-restart llama-status llama-logs llama-models

llama-render:
	python scripts/llamacpp.py render

llama-command:
	python scripts/llamacpp.py print-command

llama-run:
	python scripts/llamacpp.py run

llama-install-user:
	python scripts/llamacpp.py install-user-service

llama-start:
	systemctl --user start llamacpp-router.service

llama-stop:
	systemctl --user stop llamacpp-router.service

llama-restart:
	systemctl --user restart llamacpp-router.service

llama-status:
	systemctl --user status llamacpp-router.service --no-pager

llama-logs:
	journalctl --user -u llamacpp-router.service -f

llama-models:
	curl -s http://localhost:9090/v1/models
