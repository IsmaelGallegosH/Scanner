"""CLI: recompilar reglas de aprendizaje desde pares.jsonl."""

from __future__ import annotations

from scanner.paths import bootstrap

bootstrap()

from scanner.servicios.aprendizaje_servicio import (  # noqa: E402
    compilar_reglas,
    ruta_reglas,
)


def main() -> int:
    reglas = compilar_reglas()
    n = len(reglas.get("sustituciones") or {})
    print(f"Reglas compiladas: {n} sustituciones")
    print(f"Archivo: {ruta_reglas()}")
    top = sorted(
        (reglas.get("detalle") or {}).items(),
        key=lambda kv: int(kv[1].get("count", 0)) if isinstance(kv[1], dict) else 0,
        reverse=True,
    )[:20]
    for malo, info in top:
        if isinstance(info, dict):
            print(f"  {malo!r} → {info.get('a')!r}  (n={info.get('count')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
