# Dashboard web (GitHub Pages) — puesta en marcha

El dashboard es una página estática (`docs/index.html`) publicada con **GitHub Pages**:
no tiene servidor, así que **nunca se duerme** y carga al instante. El robot actualiza sus
datos (`docs/data.json`) y las fichas (`docs/fichas/`) cada vez que corre, con
`construir_sitio.py`.

Para generar fichas desde la página (con clave y correo) se usa un **Cloudflare Worker**
gratuito (`worker/worker.js`) que guarda el token de GitHub y dispara el robot. La página
nunca ve el token.

```
Página (GitHub Pages) ──POST /generar──▶ Worker (Cloudflare) ──API──▶ Robot (GitHub Actions)
        ▲                                                                 │
        └──────────── docs/data.json + docs/fichas/ (commit del robot) ◀──┘
```

## 1. Hacer el repositorio público
GitHub → repo → **Settings → General → Danger Zone → Change visibility → Public**.
El código no contiene contraseñas (están en *Secrets*) y los datos son públicos de INEGI.

## 2. Activar GitHub Pages
**Settings → Pages → Build and deployment**: Source = *Deploy from a branch*,
Branch = `main`, carpeta = `/docs` → **Save**. En 1–2 minutos queda en
`https://pacotinoco.github.io/Enoe-Report/`.

Después corre el robot una vez (Actions → Robot ENOE Jalisco → Run workflow) para que
genere `docs/data.json`.

## 3. Crear el Worker (para el botón "Generar ficha")
1. Crear cuenta gratis en https://dash.cloudflare.com → **Workers & Pages → Create →
   Create Worker** → nombre `enoe-robot` → **Deploy**.
2. **Edit code**: borrar lo que trae, pegar el contenido de `worker/worker.js` → **Deploy**.
3. **Settings → Variables and Secrets** → agregar:

   | Nombre | Tipo | Valor |
   |---|---|---|
   | `GH_TOKEN` | Secret | token de GitHub con *Actions: Read and write* sobre el repo (puede ser el mismo de Streamlit) |
   | `CLAVE` | Secret | la clave que escribirán los usuarios |
   | `REPO` | Text | `PacoTinoco/Enoe-Report` |
   | `ORIGEN` | Text | `https://pacotinoco.github.io` |

4. Copiar la URL del Worker (ej. `https://enoe-robot.<tu-subdominio>.workers.dev`) y
   ponerla en `docs/index.html`, en la línea `const WORKER_URL = "";`. Hacer commit y push.

## 4. Uso
- **Fichas → Generar una ficha**: trimestre, correo (opcional), clave. La ficha llega al
  correo escrito **y** a la lista fija (`DESTINATARIOS`), y aparece en la página en 1–2 min.
- **Borrar** una ficha: en su tarjeta, *Borrar* → clave.
- Sin Worker configurado la página funciona igual (consulta y descargas); solo se ocultan
  generar y borrar.

## Probar en local
```bash
python construir_sitio.py
python -m http.server -d docs 8000      # abrir http://localhost:8000
```

## Seguimiento del robot

La sección **Seguimiento del robot** muestra la próxima publicación esperada de INEGI (según
`calendario_enoe.json`), cómo busca el robot y un historial de revisiones. Cada ejecución del robot
anota una línea en `historial_robot.json` (fecha, quién la disparó, resultado y detalle; máximo 90) y
`construir_sitio.py` la incluye en `docs/data.json`. Además, la página consulta la API pública de
GitHub para mostrar también ejecuciones que fallaron antes de poder escribir su detalle.

Cada ficha muestra su **fecha de generación** (guardada en `procesados.json`).

