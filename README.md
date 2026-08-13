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

## Ollama (post-corrección LLM)

Ollama es un motor local de modelos de IA. En Scanner se usa **después** del OCR y de las reglas aprendidas para corregir más errores de reconocimiento.

### Instalación del servicio

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b
# comprobar
curl -s http://127.0.0.1:11434/api/tags
```

### Botón en la interfaz

En la barra de herramientas hay un botón conmutable **Ollama**:

| Estado | Efecto |
|--------|--------|
| OFF (por defecto) | Solo PaddleOCR + reglas aprendidas. Más rápido. |
| ON | Tras cada OCR página/libro, llama a `qwen2.5:3b` (puede tardar en CPU). |

Si activas el botón y el daemon no responde, la app avisa y lo deja en OFF.

El flag se guarda en `Sistema/config.yaml` → `aprendizaje.ollama.enabled`.

### Flujo al hacer OCR con Ollama ON

1. Paddle genera el texto bruto → `pagina_XXX.raw.txt`.
2. Se aplican las **reglas** aprendidas de tus correcciones.
3. Ollama recibe ese texto (+ pocos ejemplos few-shot de tus pares) y devuelve una corrección.
4. El resultado se muestra en el editor y en `pagina_XXX.txt`.
5. Al **Guardar** con aprendizaje, se sigue comparando contra el `.raw.txt` (las reglas mejoran igual).

### Qué no hace Ollama aquí

- No sustituye el checkbox *Usar como ejemplo de aprendizaje*.
- No aprende del `.tex`.
- No reentrena PaddleOCR.
- Si el servicio cae con el botón ON, el OCR continúa solo con reglas.

### Comprobar

```bash
export PYTHONPATH=Libreria:Sistema
python -m scanner.cli.aprender_estado
```

Debes ver `"ollama": { "enabled": true, "daemon_ok": true, "disponible": true }`.
