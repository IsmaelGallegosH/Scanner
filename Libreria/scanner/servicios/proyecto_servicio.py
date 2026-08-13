"""Organización de carpetas por documento (mismo nombre del archivo)."""

from __future__ import annotations

import re
from pathlib import Path

from config_loader import get_paths, load_config

_VERSION_RE = re.compile(r"^(?P<nombre>.+)_v(?P<num>\d+)\.txt$", re.IGNORECASE)
_VERSION_ANY_RE = re.compile(r"^(?P<nombre>.+)_v(?P<num>\d+)\.(txt|tex|pdf)$", re.IGNORECASE)


def nombre_proyecto(documento: Path) -> str:
    """Usa el nombre del archivo sin extensión (orden por libro)."""
    nombre = documento.stem.strip() or "documento"
    return nombre.replace("/", "_").replace("\\", "_").replace("..", "_")


def sanitizar_nombre(nombre: str) -> str:
    limpio = nombre.strip()
    limpio = re.sub(r"[^\w\- áéíóúÁÉÍÓÚñÑüÜ]+", "_", limpio, flags=re.UNICODE)
    limpio = re.sub(r"\s+", "_", limpio).strip("._")
    return limpio or "version"


def carpeta_proyecto(documento: Path, config: dict | None = None) -> Path:
    """
    Libreria/salida/<nombre_archivo>/
      paginas/
      ocr/
      versiones/
      _latex/
    """
    cfg = config or load_config()
    rutas = get_paths(cfg)
    base = rutas["salida"] / nombre_proyecto(documento)
    (base / "paginas").mkdir(parents=True, exist_ok=True)
    (base / "ocr").mkdir(parents=True, exist_ok=True)
    (base / "versiones").mkdir(parents=True, exist_ok=True)
    (base / "_latex").mkdir(parents=True, exist_ok=True)
    (base / "aprendizaje").mkdir(parents=True, exist_ok=True)
    return base


def carpeta_paginas(documento: Path, config: dict | None = None) -> Path:
    return carpeta_proyecto(documento, config) / "paginas"


def carpeta_ocr(documento: Path, config: dict | None = None) -> Path:
    return carpeta_proyecto(documento, config) / "ocr"


def carpeta_versiones(documento: Path, config: dict | None = None) -> Path:
    destino = carpeta_proyecto(documento, config) / "versiones"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def ruta_reescrito(documento: Path, config: dict | None = None) -> Path:
    return carpeta_proyecto(documento, config) / "reescrito.txt"


def ruta_ocr_pagina(documento: Path, indice: int, config: dict | None = None) -> Path:
    """índice base 0. Texto post-procesado / editable."""
    return carpeta_ocr(documento, config) / f"pagina_{indice + 1:03d}.txt"


def ruta_ocr_pagina_raw(documento: Path, indice: int, config: dict | None = None) -> Path:
    """OCR bruto de Paddle (sin postproceso ni ediciones humanas)."""
    return carpeta_ocr(documento, config) / f"pagina_{indice + 1:03d}.raw.txt"


def guardar_ocr_pagina(
    documento: Path,
    indice: int,
    texto_raw: str,
    texto_procesado: str | None = None,
    config: dict | None = None,
) -> tuple[Path, Path]:
    """Escribe .raw.txt y .txt (procesado). Devuelve (raw, procesado)."""
    raw_path = ruta_ocr_pagina_raw(documento, indice, config)
    txt_path = ruta_ocr_pagina(documento, indice, config)
    raw_path.write_text((texto_raw or "") + "\n", encoding="utf-8")
    cuerpo = texto_procesado if texto_procesado is not None else texto_raw
    txt_path.write_text((cuerpo or "") + "\n", encoding="utf-8")
    return raw_path, txt_path


def cargar_textos_ocr_dir(
    documento: Path,
    total: int | None = None,
    config: dict | None = None,
) -> list[str]:
    """Carga pagina_XXX.txt (no .raw) de ocr/ en orden. Rellena hasta total si se indica."""
    ocr_dir = carpeta_ocr(documento, config)
    por_idx: dict[int, str] = {}
    if ocr_dir.is_dir():
        for archivo in ocr_dir.glob("pagina_*.txt"):
            if archivo.name.endswith(".raw.txt"):
                continue
            m = re.match(r"^pagina_(\d+)\.txt$", archivo.name, re.IGNORECASE)
            if not m:
                continue
            idx = int(m.group(1)) - 1
            if idx < 0:
                continue
            por_idx[idx] = archivo.read_text(encoding="utf-8").strip()

    if not por_idx and not total:
        return []
    n = max(por_idx.keys(), default=-1) + 1
    if total is not None:
        n = max(n, total)
    return [por_idx.get(i, "") for i in range(n)]


def siguiente_version(documento: Path, nombre_base: str, config: dict | None = None) -> int:
    """Devuelve el siguiente número de versión libre para un nombre base."""
    seguro = sanitizar_nombre(nombre_base)
    carpeta = carpeta_versiones(documento, config)
    max_n = 0
    for archivo in carpeta.glob("*.txt"):
        m = _VERSION_RE.match(archivo.name)
        if not m:
            continue
        if sanitizar_nombre(m.group("nombre")) == seguro:
            max_n = max(max_n, int(m.group("num")))
    return max_n + 1


def _stem_version(nombre: str, version: int) -> str:
    return f"{sanitizar_nombre(nombre)}_v{int(version)}"


def ruta_version(
    documento: Path,
    nombre: str,
    version: int,
    config: dict | None = None,
) -> Path:
    return carpeta_versiones(documento, config) / f"{_stem_version(nombre, version)}.txt"


def ruta_version_tex(
    documento: Path,
    nombre: str,
    version: int,
    config: dict | None = None,
) -> Path:
    return carpeta_versiones(documento, config) / f"{_stem_version(nombre, version)}.tex"


def ruta_version_pdf(
    documento: Path,
    nombre: str,
    version: int,
    config: dict | None = None,
) -> Path:
    return carpeta_versiones(documento, config) / f"{_stem_version(nombre, version)}.pdf"


def carpeta_latex_build(
    documento: Path,
    nombre: str,
    version: int,
    config: dict | None = None,
) -> Path:
    destino = carpeta_proyecto(documento, config) / "_latex" / _stem_version(nombre, version)
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def listar_versiones_tex(documento: Path, config: dict | None = None) -> list[Path]:
    return sorted(carpeta_versiones(documento, config).glob("*_v*.tex"))


def listar_versiones_txt(documento: Path, config: dict | None = None) -> list[Path]:
    return sorted(carpeta_versiones(documento, config).glob("*_v*.txt"))


def parse_stem_version(ruta: Path) -> tuple[str, int] | None:
    m = _VERSION_ANY_RE.match(ruta.name)
    if not m:
        return None
    return m.group("nombre"), int(m.group("num"))


def documento_desde_ruta_procesada(ruta: Path, config: dict | None = None) -> Path:
    """
    A partir de un .txt/.tex/.pdf en salida/<libro>/... recupera el Path
    lógico del documento (PDF en entrada si existe).
    """
    cfg = config or load_config()
    rutas = get_paths(cfg)
    salida = rutas["salida"].resolve()
    actual = ruta.resolve()

    try:
        rel = actual.relative_to(salida)
    except ValueError as exc:
        raise ValueError(f"El archivo no está bajo salida/: {ruta}") from exc

    libro = rel.parts[0] if rel.parts else actual.stem
    pdf = rutas["entrada"] / f"{libro}.pdf"
    if pdf.is_file():
        return pdf
    # Path sintético: solo importa el stem para carpeta_proyecto
    return Path(f"/scanner/documentos/{libro}.pdf")


def listar_textos_procesados(config: dict | None = None) -> list[Path]:
    """Todos los .txt útiles (versiones, ocr, reescrito) bajo salida/."""
    cfg = config or load_config()
    salida = get_paths(cfg)["salida"]
    if not salida.is_dir():
        return []
    hallazgos: list[Path] = []
    for libro_dir in sorted(p for p in salida.iterdir() if p.is_dir()):
        reescrito = libro_dir / "reescrito.txt"
        if reescrito.is_file():
            hallazgos.append(reescrito)
        ocr = libro_dir / "ocr"
        if ocr.is_dir():
            hallazgos.extend(
                sorted(p for p in ocr.glob("*.txt") if not p.name.endswith(".raw.txt"))
            )
        versiones = libro_dir / "versiones"
        if versiones.is_dir():
            hallazgos.extend(sorted(versiones.glob("*_v*.txt")))
    return hallazgos
