#!/usr/bin/env bash
# Lanza la interfaz de escritorio Scanner
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/Sistema/.venv/bin/activate"

if [[ -n "${WAYLAND_DISPLAY:-}" && -z "${QT_QPA_PLATFORM:-}" ]]; then
  export QT_QPA_PLATFORM=wayland
elif [[ -z "${QT_QPA_PLATFORM:-}" ]]; then
  export QT_QPA_PLATFORM=xcb
fi

export PYTHONPATH="${ROOT}/Libreria:${ROOT}/Sistema:${PYTHONPATH:-}"
LOG="${ROOT}/Sistema/scanner_ui.log"
exec python -m scanner >>"${LOG}" 2>&1
