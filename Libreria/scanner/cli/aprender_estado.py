"""CLI: estado del corpus de aprendizaje y Ollama."""

from __future__ import annotations

import json

from scanner.paths import bootstrap

bootstrap()

from scanner.servicios.aprendizaje_servicio import estado_aprendizaje  # noqa: E402


def main() -> int:
    estado = estado_aprendizaje()
    print(json.dumps(estado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
