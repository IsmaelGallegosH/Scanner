"""CLI: OCR de un PDF completo (lote sin interfaz)."""

from __future__ import annotations

import argparse
from pathlib import Path

from scanner.paths import bootstrap

bootstrap()

from config_loader import get_paths  # noqa: E402
from scanner.servicios.ocr_servicio import ocr_pdf, unir_paginas  # noqa: E402
from scanner.servicios.proyecto_servicio import (  # noqa: E402
    carpeta_proyecto,
    guardar_ocr_pagina,
    ruta_reescrito,
)
from scanner.servicios.latex_servicio import generar_tex  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR de un PDF escaneado")
    parser.add_argument("pdf", nargs="?", help="Ruta al PDF")
    parser.add_argument("-o", "--salida", help="Archivo .txt de salida")
    args = parser.parse_args()

    rutas = get_paths()
    rutas["entrada"].mkdir(parents=True, exist_ok=True)
    rutas["salida"].mkdir(parents=True, exist_ok=True)

    if args.pdf:
        pdf = Path(args.pdf).expanduser().resolve()
    else:
        candidatos = sorted(rutas["entrada"].glob("*.pdf"))
        if not candidatos:
            print(f"No hay PDF en {rutas['entrada']}")
            return 1
        pdf = candidatos[0]

    if not pdf.is_file():
        print(f"No existe: {pdf}")
        return 1

    proyecto = carpeta_proyecto(pdf)
    print(f"Proyecto: {proyecto}")

    def progreso(actual: int, total: int, mensaje: str) -> None:
        print(f"[{actual}/{total}] {mensaje}", flush=True)

    print(f"Procesando: {pdf}")
    pares = ocr_pdf(pdf, callback_progreso=progreso)
    procesados = [p for _, p in pares]
    contenido = unir_paginas(procesados)

    for i, (raw, proc) in enumerate(pares):
        guardar_ocr_pagina(pdf, i, raw, proc)

    if args.salida:
        salida = Path(args.salida).expanduser().resolve()
        salida.parent.mkdir(parents=True, exist_ok=True)
    else:
        salida = ruta_reescrito(pdf)

    salida.write_text(contenido, encoding="utf-8")
    # Versión inicial LaTeX (sin compilar)
    try:
        tex = generar_tex(pdf, "libro_completo", 1, contenido)
        print(f"LaTeX: {tex}")
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso LaTeX: {exc}")

    print(f"Guardado: {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
