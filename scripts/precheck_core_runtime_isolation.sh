#!/usr/bin/env bash

set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export NEMU_SCRIPT_NAME="${0##*/}"
exec python3 "${SCRIPT_DIR}/precheck_core_runtime_isolation.py" "$@"
