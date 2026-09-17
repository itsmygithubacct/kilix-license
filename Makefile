.PHONY: sync test build check hygiene

UV ?= uv
PYTHON_VERSION ?= 3.12.8
DIST ?= dist
NSS_HOME := $(shell python3 -c 'import os,pwd; print(pwd.getpwuid(os.getuid()).pw_dir)')
export UV_PYTHON_INSTALL_DIR ?= $(NSS_HOME)/.local/share/uv/python
export UV_CACHE_DIR ?= $(NSS_HOME)/.cache/uv
export PYTHONPATH := src:tests/support

sync:
	$(UV) sync --frozen --python $(PYTHON_VERSION)

test:
	@set -eu; \
	scratch=$$(mktemp -d "$${TMPDIR:-/tmp}/kilix-license-check.XXXXXX"); \
	mkdir -p "$$scratch/home" "$$scratch/xdg-cache" "$$scratch/xdg-config" \
	  "$$scratch/xdg-data" "$$scratch/xdg-state" "$$scratch/xdg-runtime" \
	  "$$scratch/kilix-data" "$$scratch/kilix-storage" "$$scratch/kilix-home" \
	  "$$scratch/gpu-terminal" "$$scratch/candidate" "$$scratch/tmp"; \
	trap 'rm -rf "$$scratch"' EXIT; \
	HOME="$$scratch/home" \
	XDG_CACHE_HOME="$$scratch/xdg-cache" \
	XDG_CONFIG_HOME="$$scratch/xdg-config" \
	XDG_DATA_HOME="$$scratch/xdg-data" \
	XDG_STATE_HOME="$$scratch/xdg-state" \
	XDG_RUNTIME_DIR="$$scratch/xdg-runtime" \
	KILIX_DATA_HOME="$$scratch/kilix-data" \
	KILIX_STORAGE_HOME="$$scratch/kilix-storage" \
	KILIX_HOME="$$scratch/kilix-home" \
	GPU_TERMINAL_HOME="$$scratch/gpu-terminal" \
	CANDIDATE_SCRATCH_ROOT="$$scratch/candidate" \
	TMPDIR="$$scratch/tmp" \
	PYTHONPATH="src:tests/support" \
	UV_PYTHON_INSTALL_DIR="$(UV_PYTHON_INSTALL_DIR)" \
	UV_CACHE_DIR="$(UV_CACHE_DIR)" \
	$(UV) run --frozen --no-sync --python $(PYTHON_VERSION) \
		python -m unittest discover -s tests -v

# The gate must fail on a packaging defect. `test` runs against PYTHONPATH=src
# and would pass on a tree that cannot produce an artifact.
build:
	rm -rf $(DIST)
	$(UV) build --out-dir $(DIST)
	@set -eu; \
	sdist=$$(ls $(DIST)/*.tar.gz 2>/dev/null | wc -l); \
	wheel=$$(ls $(DIST)/*.whl 2>/dev/null | wc -l); \
	printf 'packaging artifacts: sdist %s/1, wheel %s/1\n' "$$sdist" "$$wheel"; \
	test "$$sdist" -eq 1; \
	test "$$wheel" -eq 1; \
	venv=$$(mktemp -d "$${TMPDIR:-/tmp}/kilix-license-install.XXXXXX"); \
	trap 'rm -rf "$$venv"' EXIT; \
	$(UV) venv "$$venv" --python $(PYTHON_VERSION) >/dev/null; \
	$(UV) pip install --python "$$venv/bin/python" $(DIST)/*.whl >/dev/null; \
	"$$venv/bin/python" -c 'import kilix_license, sys; \
	 sys.exit(0 if kilix_license.__version__ else 1)'; \
	printf 'installed wheel imports: 1/1\n'

check: sync test build

hygiene:
	hygiene-scan --recurse
