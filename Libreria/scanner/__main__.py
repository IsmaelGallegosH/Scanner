"""Punto de entrada: python -m scanner"""

from __future__ import annotations

from scanner.paths import bootstrap

bootstrap()

from scanner.ui.app_escritorio import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
