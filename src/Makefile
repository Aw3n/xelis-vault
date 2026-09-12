# XELIS Vault — operator automation
PYTHON ?= python3
SCRIPTS := scripts

.PHONY: help check bundle chunks syntax test-mock install-deps

help:
	@echo "XELIS Vault targets:"
	@echo "  make check        static consistency (hashes, chunks, syntax)"
	@echo "  make bundle       regenerate network/testnet.json from deployment_state"
	@echo "  make chunks       recompile contracts + write docs/entry_chunk_ids.json"
	@echo "  make syntax       py_compile all Python"
	@echo "  make test-mock    offline integration suite"
	@echo "  make install-deps pip install -r requirements.txt"

check:
	$(PYTHON) $(SCRIPTS)/check_consistency.py

bundle:
	$(PYTHON) $(SCRIPTS)/sync_network_bundle.py

chunks:
	$(PYTHON) $(SCRIPTS)/gen_chunk_map.py

syntax:
	$(PYTHON) -m py_compile $(SCRIPTS)/*.py deploy/*.py tests/*.py

test-mock:
	$(PYTHON) tests/test_all_contracts.py --mock

install-deps:
	$(PYTHON) -m pip install --break-system-packages -r requirements.txt
