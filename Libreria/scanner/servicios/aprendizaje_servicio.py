"""Aprendizaje human-in-the-loop desde correcciones OCR.

Capa A: pares OCR→corrección → reglas de sustitución + léxico.
Capa B: Ollama few-shot opcional.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from config_loader import get_paths, load_config

_WORD_RE = re.compile(r"\S+")
_LEX_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}")
_CACHE_REGLAS: dict[str, Any] | None = None


def _cfg_aprendizaje(config: dict | None = None) -> dict:
    return (config or load_config()).get("aprendizaje", {}) or {}


def aprendizaje_habilitado(config: dict | None = None) -> bool:
    return bool(_cfg_aprendizaje(config).get("habilitado", True))


def carpeta_aprendizaje_global(config: dict | None = None) -> Path:
    rutas = get_paths(config)
    base = rutas["sistema"] / "aprendizaje"
    base.mkdir(parents=True, exist_ok=True)
    return base


def ruta_pares_global(config: dict | None = None) -> Path:
    return carpeta_aprendizaje_global(config) / "pares.jsonl"


def ruta_reglas(config: dict | None = None) -> Path:
    return carpeta_aprendizaje_global(config) / "reglas.json"


def ruta_lexico(config: dict | None = None) -> Path:
    return carpeta_aprendizaje_global(config) / "lexico.txt"


def carpeta_aprendizaje_libro(documento: Path, config: dict | None = None) -> Path:
    from scanner.servicios.proyecto_servicio import carpeta_proyecto

    destino = carpeta_proyecto(documento, config) / "aprendizaje"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def ruta_pares_libro(documento: Path, config: dict | None = None) -> Path:
    return carpeta_aprendizaje_libro(documento, config) / "pares.jsonl"


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalizar_ws(texto: str) -> str:
    return re.sub(r"[ \t]+", " ", texto.replace("\r\n", "\n").replace("\r", "\n"))


def alinear_y_extraer(ocr: str, corregido: str) -> list[tuple[str, str]]:
    """Extrae pares malo→bueno a nivel palabra con SequenceMatcher."""
    a = _WORD_RE.findall(ocr or "")
    b = _WORD_RE.findall(corregido or "")
    if not a and not b:
        return []
    pares: list[tuple[str, str]] = []
    sm = SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        malo = " ".join(a[i1:i2]).strip()
        bueno = " ".join(b[j1:j2]).strip()
        if not malo and not bueno:
            continue
        # Sustitución 1:1 o bloque corto (evitar párrafos enteros)
        if tag == "replace" and malo and bueno:
            palabras_m = malo.split()
            palabras_b = bueno.split()
            if len(palabras_m) == len(palabras_b) and len(palabras_m) <= 6:
                for m, g in zip(palabras_m, palabras_b):
                    if m != g:
                        pares.append((m, g))
            elif len(malo) <= 48 and len(bueno) <= 48:
                pares.append((malo, bueno))
        elif tag == "delete" and malo and len(malo) <= 24:
            # borrados sueltos no generan regla de sustitución
            continue
        elif tag == "insert" and bueno and len(bueno) <= 24:
            continue
    return pares


def _append_jsonl(ruta: Path, registro: dict[str, Any]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _extraer_lexico(texto: str) -> set[str]:
    return {m.group(0) for m in _LEX_RE.finditer(texto or "")}


def _actualizar_lexico(palabras: set[str], config: dict | None = None) -> None:
    if not palabras:
        return
    ruta = ruta_lexico(config)
    existentes: set[str] = set()
    if ruta.is_file():
        existentes = {ln.strip() for ln in ruta.read_text(encoding="utf-8").splitlines() if ln.strip()}
    unidos = existentes | palabras
    ruta.write_text("\n".join(sorted(unidos, key=str.casefold)) + "\n", encoding="utf-8")


def registrar_correccion(
    ocr: str,
    corregido: str,
    *,
    documento: Path | None = None,
    pagina: int | None = None,
    fuente: str = "guardar",
    config: dict | None = None,
) -> dict[str, Any]:
    """
    Guarda un par OCR→corrección si difieren.
    Devuelve resumen {registrado, pares_extraidos, ...}.
    """
    cfg = config or load_config()
    if not aprendizaje_habilitado(cfg):
        return {"registrado": False, "razon": "deshabilitado"}

    bruto = _normalizar_ws(ocr or "").strip()
    limpio = _normalizar_ws(corregido or "").strip()
    if not bruto or not limpio or bruto == limpio:
        return {"registrado": False, "razon": "sin_diferencias"}

    pares = alinear_y_extraer(bruto, limpio)
    from scanner.servicios.proyecto_servicio import nombre_proyecto

    libro = nombre_proyecto(documento) if documento else None
    registro = {
        "ocr": bruto,
        "corregido": limpio,
        "sustituciones": [{"de": a, "a": b} for a, b in pares],
        "fuente": fuente,
        "libro": libro,
        "pagina": pagina,
        "fecha": _ahora_iso(),
    }
    _append_jsonl(ruta_pares_global(cfg), registro)
    if documento is not None:
        _append_jsonl(ruta_pares_libro(documento, cfg), registro)

    _actualizar_lexico(_extraer_lexico(limpio), cfg)
    reglas = compilar_reglas(cfg)
    return {
        "registrado": True,
        "pares_extraidos": len(pares),
        "reglas": len(reglas.get("sustituciones", {})),
    }


def iterar_pares(config: dict | None = None) -> list[dict[str, Any]]:
    ruta = ruta_pares_global(config)
    if not ruta.is_file():
        return []
    out: list[dict[str, Any]] = []
    with ruta.open(encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea:
                continue
            try:
                out.append(json.loads(linea))
            except json.JSONDecodeError:
                continue
    return out


def compilar_reglas(config: dict | None = None) -> dict[str, Any]:
    """Recompila reglas.json desde pares.jsonl."""
    global _CACHE_REGLAS
    cfg = config or load_config()
    apr = _cfg_aprendizaje(cfg)
    min_count = int(apr.get("min_count", 2))

    contadores: dict[str, Counter[str]] = defaultdict(Counter)
    for reg in iterar_pares(cfg):
        for s in reg.get("sustituciones") or []:
            de = str(s.get("de", "")).strip()
            a = str(s.get("a", "")).strip()
            if de and a and de != a:
                contadores[de][a] += 1
        # También pares implícitos del registro completo si no hay lista
        if not reg.get("sustituciones"):
            for de, a in alinear_y_extraer(reg.get("ocr", ""), reg.get("corregido", "")):
                contadores[de][a] += 1

    sustituciones: dict[str, str] = {}
    detalle: dict[str, Any] = {}
    for malo, destinos in contadores.items():
        bueno, n = destinos.most_common(1)[0]
        segundo = destinos.most_common(2)[1][1] if len(destinos) > 1 else 0
        # Ambiguo si el segundo rivaliza (≥50% del primero)
        if n < min_count:
            continue
        if segundo and segundo * 2 >= n:
            continue
        sustituciones[malo] = bueno
        detalle[malo] = {"a": bueno, "count": n}

    payload = {
        "min_count": min_count,
        "actualizado": _ahora_iso(),
        "sustituciones": sustituciones,
        "detalle": detalle,
    }
    ruta = ruta_reglas(cfg)
    ruta.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _CACHE_REGLAS = payload
    return payload


def cargar_reglas(config: dict | None = None, *, forzar: bool = False) -> dict[str, Any]:
    global _CACHE_REGLAS
    if _CACHE_REGLAS is not None and not forzar:
        return _CACHE_REGLAS
    ruta = ruta_reglas(config)
    if not ruta.is_file():
        _CACHE_REGLAS = {"sustituciones": {}, "min_count": 2}
        return _CACHE_REGLAS
    try:
        _CACHE_REGLAS = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _CACHE_REGLAS = {"sustituciones": {}, "min_count": 2}
    return _CACHE_REGLAS


def _unir_guiones_corte(texto: str) -> str:
    # "pala-\nbra" / "pala- bra" → "palabra"
    return re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", texto)


def _aplicar_sustituciones(texto: str, sustituciones: dict[str, str]) -> str:
    if not sustituciones:
        return texto

    # Ordenar por longitud descendente para preferir frases multi-palabra
    items = sorted(sustituciones.items(), key=lambda kv: len(kv[0]), reverse=True)

    def reemplazar_token(tok: str) -> str:
        if tok in sustituciones:
            return sustituciones[tok]
        # Variante sin puntuación final pegada
        m = re.match(r"^(\W*)(.*?)(\W*)$", tok, re.UNICODE)
        if not m:
            return tok
        pref, nucleo, suf = m.groups()
        if nucleo in sustituciones:
            return pref + sustituciones[nucleo] + suf
        return tok

    # Primero frases (contienen espacio)
    out = texto
    for malo, bueno in items:
        if " " in malo:
            out = out.replace(malo, bueno)

    # Luego tokens
    piezas: list[str] = []
    ultimo = 0
    for m in _WORD_RE.finditer(out):
        if m.start() > ultimo:
            piezas.append(out[ultimo : m.start()])
        piezas.append(reemplazar_token(m.group(0)))
        ultimo = m.end()
    if ultimo < len(out):
        piezas.append(out[ultimo:])
    return "".join(piezas)


def _ejemplos_fewshot(texto: str, max_n: int, config: dict | None = None) -> list[tuple[str, str]]:
    """Elige pares de corrección similares (solapamiento de tokens)."""
    tokens = set(_WORD_RE.findall(texto.lower()))
    if not tokens:
        return []
    candidatos: list[tuple[int, str, str]] = []
    for reg in iterar_pares(config):
        ocr = (reg.get("ocr") or "").strip()
        corr = (reg.get("corregido") or "").strip()
        if not ocr or not corr or ocr == corr:
            continue
        # Preferir fragmentos cortos como ejemplo
        if len(ocr) > 800:
            ocr = ocr[:800]
            corr = corr[:800]
        solape = len(tokens & set(t.lower() for t in _WORD_RE.findall(ocr)))
        if solape:
            candidatos.append((solape, ocr, corr))
    candidatos.sort(key=lambda x: x[0], reverse=True)
    vistos: set[str] = set()
    out: list[tuple[str, str]] = []
    for _, ocr, corr in candidatos:
        clave = ocr[:120]
        if clave in vistos:
            continue
        vistos.add(clave)
        out.append((ocr, corr))
        if len(out) >= max_n:
            break
    return out


def ollama_disponible(config: dict | None = None) -> bool:
    apr = _cfg_aprendizaje(config)
    ollama = apr.get("ollama") or {}
    if not ollama.get("enabled", False):
        return False
    url = str(ollama.get("url", "http://127.0.0.1:11434")).rstrip("/")
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def sugerir_con_ollama(texto: str, config: dict | None = None) -> str | None:
    """Post-corrección vía Ollama. None si deshabilitado o falla."""
    cfg = config or load_config()
    apr = _cfg_aprendizaje(cfg)
    ollama = apr.get("ollama") or {}
    if not ollama.get("enabled", False):
        return None
    bruto = (texto or "").strip()
    if not bruto:
        return None

    url = str(ollama.get("url", "http://127.0.0.1:11434")).rstrip("/")
    modelo = str(ollama.get("modelo", "qwen2.5:3b"))
    max_ej = int(ollama.get("max_ejemplos_fewshot", 5))
    timeout = float(ollama.get("timeout_seg", 60))

    ejemplos = _ejemplos_fewshot(bruto, max_ej, cfg)
    bloques = [
        "Eres un corrector de errores de OCR en español.",
        "Corrige solo errores de reconocimiento (letras confusas, acentos, guiones).",
        "No reescribas el estilo ni inventes contenido. Devuelve únicamente el texto corregido.",
    ]
    for i, (ocr_ej, corr_ej) in enumerate(ejemplos, start=1):
        bloques.append(f"\nEjemplo {i} OCR:\n{ocr_ej}\nEjemplo {i} corregido:\n{corr_ej}")
    bloques.append(f"\nOCR a corregir:\n{bruto}")

    payload = {
        "model": modelo,
        "prompt": "\n".join(bloques),
        "stream": False,
        "options": {"temperature": 0.1},
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        respuesta = (body.get("response") or "").strip()
        return respuesta or None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def aplicar_postproceso(texto: str, config: dict | None = None) -> str:
    """Aplica reglas aprendidas y, si está activo, Ollama."""
    cfg = config or load_config()
    if not aprendizaje_habilitado(cfg):
        return texto

    out = _unir_guiones_corte(texto or "")
    out = re.sub(r"[ \t]+", " ", out)
    reglas = cargar_reglas(cfg)
    sust = reglas.get("sustituciones") or {}
    out = _aplicar_sustituciones(out, sust)

    sugerido = sugerir_con_ollama(out, cfg)
    if sugerido:
        out = sugerido
    return out.strip()


def estado_aprendizaje(config: dict | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    pares = iterar_pares(cfg)
    reglas = cargar_reglas(cfg, forzar=True)
    sust = reglas.get("sustituciones") or {}
    top = sorted(
        ((k, v) for k, v in (reglas.get("detalle") or {}).items()),
        key=lambda kv: int(kv[1].get("count", 0)) if isinstance(kv[1], dict) else 0,
        reverse=True,
    )[:15]
    lexico = ruta_lexico(cfg)
    n_lex = 0
    if lexico.is_file():
        n_lex = sum(1 for ln in lexico.read_text(encoding="utf-8").splitlines() if ln.strip())
    ollama_cfg = (_cfg_aprendizaje(cfg).get("ollama") or {})
    return {
        "habilitado": aprendizaje_habilitado(cfg),
        "pares": len(pares),
        "reglas": len(sust),
        "lexico": n_lex,
        "top_sustituciones": [
            {"de": k, "a": v.get("a"), "count": v.get("count")} for k, v in top if isinstance(v, dict)
        ],
        "ollama": {
            "enabled": bool(ollama_cfg.get("enabled", False)),
            "modelo": ollama_cfg.get("modelo"),
            "disponible": ollama_disponible(cfg),
        },
        "rutas": {
            "pares": str(ruta_pares_global(cfg)),
            "reglas": str(ruta_reglas(cfg)),
            "lexico": str(ruta_lexico(cfg)),
        },
    }


def leer_ocr_crudo(documento: Path, indice: int, config: dict | None = None) -> str | None:
    """Preferir .raw.txt; si no existe, None (no contaminar con texto ya editado)."""
    from scanner.servicios.proyecto_servicio import ruta_ocr_pagina_raw

    raw = ruta_ocr_pagina_raw(documento, indice, config)
    if raw.is_file():
        return raw.read_text(encoding="utf-8")
    return None


def leer_ocr_crudo_libro(documento: Path, total: int, config: dict | None = None) -> str | None:
    from scanner.servicios.ocr_servicio import unir_paginas

    paginas: list[str] = []
    hay = False
    for i in range(total):
        bruto = leer_ocr_crudo(documento, i, config)
        if bruto is not None:
            hay = True
            paginas.append(bruto.strip())
        else:
            paginas.append("")
    if not hay:
        return None
    return unir_paginas(paginas)
