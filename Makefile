.PHONY: llama-render llama-command llama-run llama-install-user llama-install-commands llama-start llama-stop llama-restart llama-status llama-logs llama-models

llama-render:
	python scripts/llamacpp.py render

llama-command:
	python scripts/llamacpp.py print-command

llama-run:
	python scripts/llamacpp.py run

llama-install-user:
	python scripts/llamacpp.py install-user-service

llama-install-commands:
	python scripts/llamacpp.py install-console-commands

llama-start:
	python scripts/llamacpp.py service-start

llama-stop:
	python scripts/llamacpp.py service-stop

llama-restart:
	python scripts/llamacpp.py service-restart

llama-status:
	python scripts/llamacpp.py service-status

llama-logs:
	python scripts/llamacpp.py service-logs

llama-models:
	python scripts/llamacpp.py list-models
