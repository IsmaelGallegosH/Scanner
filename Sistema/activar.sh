#!/usr/bin/env bash
# Activa el entorno virtual del proyecto Scanner
# Uso: source /home/lorem/Documentos/Soviets/Scanner/Sistema/activar.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/.venv/bin/activate"
export SCANNER_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export SCANNER_SISTEMA="${SCRIPT_DIR}"
export SCANNER_LIBRERIA="${SCANNER_ROOT}/Libreria"
echo "Entorno Scanner activo: ${VIRTUAL_ENV}"
echo "Proyecto: ${SCANNER_ROOT}"
