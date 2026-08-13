# Scanner

Proyecto universitario de **escaneo y reescritura de libros** con PaddleOCR, editor de texto, versiones y exportación LaTeX/PDF. Incluye aprendizaje a partir de correcciones humanas.

## Estructura

```
Scanner/
├── Libreria/
│   ├── entrada/          # PDFs e imágenes a escanear (local, no en git)
│   ├── salida/           # Resultados OCR / versiones (local, no en git)
│   └── scanner/          # Código Python (UI, servicios, CLI)
└── Sistema/
    ├── config.yaml
    ├── requirements.txt
    ├── plantillas/       # Plantillas LaTeX
    ├── activar.sh
    ├── iniciar_escritorio.sh
    ├── .venv/            # Entorno virtual (local)
    ├── modelos/          # Modelos OCR (local)
    └── aprendizaje/      # Pares y reglas aprendidas (local)
```

## Requisitos

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) o `pip`
- Opcional: TeX Live (`xelatex`) para compilar libros
- Opcional: [Ollama](https://ollama.com) para post-corrección LLM

## Instalación

```bash
git clone https://github.com/IsmaelGallegosH/Scanner.git
cd Scanner

# Entorno
uv venv Sistema/.venv
source Sistema/activar.sh
uv pip install -r Sistema/requirements.txt
```

## Uso

1. Coloca un PDF en `Libreria/entrada/`.
2. Arranca la interfaz:

```bash
./Sistema/iniciar_escritorio.sh
```

3. Abre el PDF → OCR página o libro → corrige → Guardar (marca *Usar como ejemplo de aprendizaje* para enseñar reglas).

### CLI útil

```bash
export PYTHONPATH=Libreria:Sistema
python -m scanner.cli.ocr_libro Libreria/entrada/mi_libro.pdf
python -m scanner.cli.aprender_estado
python -m scanner.cli.aprender_compilar
```

## Nota sobre datos

Este repositorio **no incluye** PDFs de entrada ni resultados escaneados. Solo el código y la configuración.
