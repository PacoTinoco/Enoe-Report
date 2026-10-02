# Guía de uso — Ficha ENOE Jalisco

**Proyecto de Aplicación Profesional · Economía, ITESO · 2026**
Genera automáticamente la ficha informativa trimestral del mercado laboral de Jalisco
(Tasa de Desocupación, participación, informalidad y subocupación, con desagregación por sexo).

---

## ¿Qué hace?

Cada trimestre, cuando INEGI publica la ENOE:

1. Descarga los **microdatos** de la ENOE (datos abiertos de INEGI) del trimestre y del mismo trimestre del año anterior.
2. Calcula los indicadores de Jalisco (total, hombres y mujeres), el total nacional y las 32 entidades, con la metodología de INEGI.
3. Genera la ficha en `.txt` y `.docx` dentro de la carpeta `fichas/`.
4. Envía la ficha por correo (si está configurado).

Con el **robot** activo (ver `ROBOT.md`, guía del administrador) todo esto pasa solo: el día que INEGI publica,
la ficha llega por correo alrededor de las 06:00–06:15, sin que nadie tenga que hacer nada.
Lo que se describe abajo sirve para generarla a mano o volver a generarla.

No se necesita token del BIE ni capturar datos a mano: el ranking nacional, el top-5, la tabla regional
y el dato nacional salen de los mismos microdatos. Las cifras totales de Jalisco coinciden con las que publica INEGI
(verificado con T2 2025 y T2 2026).

---

## Contenido de la carpeta

```
enoe_jalisco/
├── pipeline_trimestral.py        ← Comando principal
├── calcular_indicadores.py       ← Descarga microdatos y calcula indicadores
├── generar_ficha.py              ← Escribe la ficha (.txt y .docx)
├── app.py                        ← Dashboard (Streamlit)
├── robot.py                      ← Robot diario: vigila la publicación y dispara la ficha
├── calendario.py                 ← Lee el calendario oficial de INEGI
├── calendario_enoe.json          ← Fechas de publicación de la ENOE trimestral
├── .github/workflows/robot.yml   ← Programación del robot en GitHub Actions
├── ROBOT.md                      ← Instalación del robot (administrador)
├── config.ejemplo.ini            ← Plantilla de config.ini (datos del correo)
├── requirements.txt              ← Paquetes de Python necesarios
├── serie_bie_jalisco.csv         ← Serie histórica de la TD (2005 – hoy), se actualiza sola
├── serie_indicadores_jalisco.csv ← Serie de TPEA, TIL1 y subocupación, se actualiza sola
├── datos/                        ← Microdatos descargados e indicadores calculados (caché)
└── fichas/                       ← Fichas generadas (ficha_AAAA_T#.txt / .docx)
```

---

## Instalación (una sola vez)

Requiere **Python 3.10 o superior**. En una terminal abierta en esta carpeta:

```bash
python -m pip install -r requirements.txt
```

Para el correo al correr a mano: copiar `config.ejemplo.ini` como `config.ini` y llenarlo:

```ini
[email]
usuario       = correo.del.proyecto@gmail.com
password      = contraseña_de_aplicación
destinatarios = persona1@inegi.org.mx, persona2@inegi.org.mx
```

> **Gmail:** la cuenta necesita verificación en dos pasos y una "contraseña de aplicación"
> (https://myaccount.google.com/apppasswords). Se recomienda que los destinatarios agreguen
> esta cuenta a sus remitentes seguros para que el correo no llegue a spam.

---

## Uso

**Opción A — Dashboard (recomendado):**

```bash
python -m streamlit run app.py
```

Se abre en el navegador. En la pestaña **⚙️ Generar ficha** basta con presionar **Generar ficha**.

En la pestaña **📄 Fichas** cada ficha muestra la fecha y hora (CDMX) en que se generó, botones de
descarga y **🗑️ Borrar ficha**. Hay un solo archivo por trimestre: al regenerarla se sobrescribe,
nunca se duplica.

**Opción B — Terminal:**

```bash
python pipeline_trimestral.py                    # detecta el trimestre más reciente publicado
python pipeline_trimestral.py --periodo 2026_T3  # un trimestre específico
```

| Opción | Qué hace |
|---|---|
| `--periodo AAAA_T#` | Trimestre a procesar (ej. `2026_T3`) |
| `--sin-email` | Genera la ficha sin mandar correo |
| `--forzar` | Rehace la ficha aunque ya se haya generado |

---

## ¿Qué se obtiene?

| Archivo | Descripción |
|---|---|
| `fichas/ficha_AAAA_T#.txt` | Ficha en texto (lista para pegar en correo o mensaje) |
| `fichas/ficha_AAAA_T#.docx` | Ficha en Word |
| `datos/indicadores_AAAA_T#.json` | Todos los indicadores calculados del trimestre |

La ficha incluye: análisis anual de la TD, comparativo con el nacional, posición entre las 32 entidades,
comparativo regional (Occidente / Centro-Bajío), indicadores complementarios y **indicadores por sexo**.

---

## Calendario de publicación

INEGI publica la ENOE trimestral a las **06:00 (hora del centro de México)**:

| Trimestre | Publicación |
|---|---|
| T3 2026 | 25 de noviembre de 2026 |
| T4 2026 | 25 de febrero de 2027 |
| T1 2027 | 27 de mayo de 2027 |

El robot actualiza estas fechas solo desde el calendario oficial
(https://www.inegi.org.mx/app/saladeprensa/calendario/). Para verlas: `python calendario.py`.

---

## Solución de problemas

| Mensaje | Causa | Solución |
|---|---|---|
| `Los microdatos de ... aún no están publicados` | INEGI todavía no publica ese trimestre | Esperar a la fecha del calendario |
| `ya fue procesado` | La ficha de ese trimestre ya existe | Usar `--forzar` (o la casilla en el dashboard) |
| `Revisión de datos falló` | Los datos descargados no tienen sentido (archivo incompleto o cambio de formato de INEGI) | Borrar el ZIP de ese trimestre en `datos/` y volver a correr; si persiste, contactar al equipo |
| Error al enviar correo | Contraseña o usuario incorrectos | Revisar `config.ini` (usar contraseña de aplicación) |

---

## Metodología

Tabla sociodemográfica (SDEM) de los microdatos ENOE; entrevistas completas, residentes habituales,
población de 15 años y más; ponderador: factor de expansión trimestral.

- **TD** = desocupados / población económicamente activa (PEA)
- **TPEA** = PEA / población de 15 años y más
- **TIL1** = ocupados en informalidad laboral / ocupados
- **Subocupación** = ocupados subocupados / ocupados

Las estimaciones por sexo a nivel estatal tienen mayor error de muestreo que el total.

---

*Proyecto de Aplicación Profesional — Economía, ITESO · 2026 · Datos: INEGI, ENOE*
