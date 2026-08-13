"""Carga la configuración del sistema Scanner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SISTEMA_DIR = Path(__file__).resolve().parent
RAIZ_PROYECTO = SISTEMA_DIR.parent
CONFIG_PATH = SISTEMA_DIR / "config.yaml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or CONFIG_PATH
    with config_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _resolver_ruta(valor: str | Path, base: Path = RAIZ_PROYECTO) -> Path:
    ruta = Path(valor).expanduser()
    if ruta.is_absolute():
        return ruta
    return (base / ruta).resolve()


def get_paths(config: dict[str, Any] | None = None) -> dict[str, Path]:
    cfg = config or load_config()
    rutas = cfg["proyecto"]["rutas"]
    return {clave: _resolver_ruta(valor) for clave, valor in rutas.items()}


if __name__ == "__main__":
    print(load_config())
    print(get_paths())
