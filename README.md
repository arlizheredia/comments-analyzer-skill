# Social Comments Analyzer: skill para agentes de IA

Versión *skill* (formato abierto `SKILL.md`) de [Social Comments Analyzer](https://github.com/arlizheredia/social-comments-analyzer), preparada para publicarse en [Agensi](https://www.agensi.io/sell). Funciona en Claude Code, Codex CLI, Cursor y en cualquier agente que lea `SKILL.md`.

El agente obtiene los comentarios de publicaciones de **Instagram, TikTok y Facebook** con las herramientas de datos de Agensi, sin que el comprador necesite claves ni cuentas de API. También acepta archivos exportados desde la app web o cualquier CSV/JSON de comentarios. Después los analiza (sentimiento, temas, enfoque, autores, preguntas sin respuesta del equipo…) y entrega un informe **HTML** (imprimible a PDF), **Excel**, **CSV**, **Markdown** y **JSON**.

## Cómo está construido

```
social-comments-analyzer/        ← esto es lo que se sube a Agensi (ZIP con SKILL.md en la raíz)
├── SKILL.md                     instrucciones para el agente + herramientas de Agensi que usa
└── scripts/
    ├── normalize.py             resultados crudos de Agensi / exportaciones → comments.json canónico
    ├── analyze.py               estadísticas, sentimiento (léxico ES/EN/PT), digest para el agente
    └── export.py                HTML, XLSX, CSV, MD, JSON
examples/                        datos de ejemplo con la forma de las respuestas de Agensi y de la app
tests/test_pipeline.py           pruebas de extremo a extremo
tools/build.py                   valida contra las reglas de Agensi y genera dist/*.zip
tools/install-local.sh           instala el skill en Claude Code para probarlo
```

Flujo: **el agente** llama a las herramientas de Agensi, guarda cada resultado tal cual, ejecuta `normalize.py` y `analyze.py`, lee el *digest*, corrige el sentimiento y clasifica el enfoque y los temas (`labels.json`), vuelve a ejecutar `analyze.py`, redacta el resumen (`summary.md`) y ejecuta `export.py`. El papel de la IA local de la app web (Qwen) lo cumple ahora el propio modelo del agente.

Decisiones impuestas por las reglas de Agensi:
- Los scripts **no hacen llamadas de red** y no pueden llamar a las herramientas de Agensi (solo el agente puede). Tampoco leen variables de entorno ni usan `subprocess`, `eval` ni `shell=True`.
- Cada script es **autocontenido**, porque Agensi lo ejecuta solo, desde un archivo temporal, y no puede leer otros archivos del paquete. Usan solo la biblioteca estándar de Python 3.8+ y menos de 20 KB de lógica cada uno.
- El `SKILL.md` no incluye precios, no pide claves de API y nombra 6 herramientas, por debajo del máximo de 10.

## Probarlo localmente

Requisitos: Python 3.8+ y, para la prueba con agente, Claude Code.

### 1. Pruebas automáticas y validación del paquete

```bash
python3 -m unittest discover -s tests -v   # 16 pruebas de extremo a extremo
python3 tools/build.py --check             # valida las reglas de Agensi sin generar el ZIP
```

### 2. Los scripts a mano, con los datos de ejemplo

```bash
mkdir -p comments-analysis
python3 social-comments-analyzer/scripts/normalize.py \
  examples/instagram-agensi.json \
  "examples/tiktok-agensi.json::https://www.tiktok.com/@marca/video/7299999999999999999" \
  examples/facebook-agensi.json examples/app-export.csv \
  -o comments-analysis/comments.json

python3 social-comments-analyzer/scripts/analyze.py comments-analysis/comments.json \
  -o comments-analysis/analysis.json --enriched comments-analysis/enriched.json \
  --digest comments-analysis/digest.jsonl --team kanasta24

python3 social-comments-analyzer/scripts/export.py comments-analysis/enriched.json \
  --analysis comments-analysis/analysis.json --formats html,xlsx,csv \
  --lang es --out-dir comments-analysis/report

xdg-open comments-analysis/report/comments.html
```

También puedes pasarle a `normalize.py` un JSON o CSV exportado desde la app web.

### 3. Con un agente real (Claude Code), sin coste

```bash
tools/install-local.sh          # enlaza el skill en ~/.claude/skills/social-comments-analyzer
claude
```

Y pídele, por ejemplo:

> Analiza los comentarios de examples/instagram-agensi.json y examples/tiktok-agensi.json, con enfoque en «quejas de servicio», y hazme un informe HTML y Excel en español.

Como el skill está enlazado, cada cambio en el código se prueba al momento. Para quitarlo: `tools/install-local.sh --remove`.

### 4. Con datos reales mediante Agensi (de pago por uso, desde tu saldo)

1. Conecta Claude Code a Agensi (el inicio de sesión se hace en el navegador; no se pega ningún token):
   ```bash
   claude mcp add --transport http agensi https://mcp.agensi.io/mcp/auth
   ```
   Dentro de `claude`, ejecuta `/mcp` y autentica Agensi. Las cuentas nuevas traen crédito gratuito que sirve para las herramientas.
2. Comprueba cada herramienta antes de publicar, como recomienda Agensi: *"Use Agensi to get the comments of https://www.instagram.com/p/…/"*. Verifica que el resultado trae los campos de texto, autor, fecha y me gusta, guárdalo en `examples/` y pásale `normalize.py`. Si algún campo no se reconoce, se añade su nombre a las listas `*_KEYS` de `normalize.py`.
3. Pide un análisis real con 1 o 2 publicaciones públicas.

## Publicar en Agensi

1. `python3 tools/build.py` genera `dist/social-comments-analyzer-<versión>.zip` con `SKILL.md` en la raíz.
2. En <https://www.agensi.io/sell>, inicia sesión con Google, activa el modo creador en los ajustes y sube el ZIP.
3. En la sección **Agensi tools** del formulario, revisa la lista que Agensi detecta a partir del `SKILL.md`. Deben quedar estas 6: *Instagram Post Comments*, *Instagram Comment Replies*, *TikTok Video Comments*, *TikTok Comment Replies*, *Facebook Post Comments* y *Facebook Comment Replies*. Resuelve cualquier aviso *“Mentioned, not added”*. Si Agensi muestra el id exacto de cada herramienta (`agensi:…`), puedes sustituir el nombre por el id en `SKILL.md`.
4. Fija el precio (gratis o desde 1 USD; recibes el 70 %). Una publicación gratuita no necesita configurar pagos.
5. Después vienen el escaneo de seguridad y una revisión manual, normalmente en menos de 24–48 h.

Para publicar una versión nueva, sube `version:` en el frontmatter, vuelve a ejecutar `tools/build.py` y sube el ZIP desde la página de edición. Agensi bloquea un ZIP idéntico al anterior.

## Limitaciones

- Solo publicaciones públicas. Las publicaciones privadas, borradas o con bloqueo regional no devuelven comentarios.
- El sentimiento de los scripts es un léxico (español, inglés, portugués) y es orientativo. El agente corrige los comentarios que lee en el *digest* (por defecto hasta 2000).
- La forma exacta de las respuestas de cada proveedor de Agensi puede variar. `normalize.py` reconoce muchas variantes y se amplía fácilmente.
