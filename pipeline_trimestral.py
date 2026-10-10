"""
pipeline_trimestral.py
======================
Orquestador trimestral ENOE · Jalisco.

Uso:
    python pipeline_trimestral.py                    # detecta el trimestre más reciente publicado
    python pipeline_trimestral.py --periodo 2026_T3  # un trimestre específico
    python pipeline_trimestral.py --forzar           # rehacer aunque ya esté procesado
    python pipeline_trimestral.py --sin-email        # generar sin mandar correo

Pasos:
    1. Determinar el período (argumento, o el más reciente con microdatos publicados)
    2. Saltar si ya fue procesado (procesados.json), salvo --forzar
    3. Calcular indicadores del período, del mismo trimestre del año anterior,
       del cierre del año anterior (T4) y del trimestre anterior
    4. Actualizar las series históricas (CSV) que usa el dashboard
    5. Generar la ficha .txt y .docx en fichas/
    6. Enviar el correo con la ficha adjunta
    7. Registrar el período como procesado
"""

import argparse
import configparser
import json
import logging
import os
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

from calendario import ahora_cdmx
from calcular_indicadores import JALISCO, calcular, publicado
from generar_ficha import generar_docx, generar_txt, preparar

BASE    = Path(__file__).parent
DATOS   = BASE / "datos"
FICHAS  = BASE / "fichas"
ESTADO  = BASE / "procesados.json"
CONFIG  = BASE / "config.ini"
SERIE_TD          = BASE / "serie_bie_jalisco.csv"
SERIE_INDICADORES = BASE / "serie_indicadores_jalisco.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("pipeline")


# ── Períodos ──────────────────────────────────────────────────────────────────

def periodo_anterior(periodo: str) -> str:
    """Mismo trimestre del año anterior."""
    anio, trim = periodo.split("_T")
    return f"{int(anio) - 1}_T{trim}"


def cierre_anio_anterior(periodo: str) -> str:
    """T4 del año anterior (cierre de diciembre)."""
    return f"{int(periodo[:4]) - 1}_T4"


def trimestre_previo(periodo: str) -> str:
    anio, trim = map(int, periodo.split("_T"))
    return f"{anio - 1}_T4" if trim == 1 else f"{anio}_T{trim - 1}"


def detectar_periodo() -> str | None:
    """El trimestre más reciente cuyos microdatos ya están publicados."""
    hoy = date.today()
    anio, trim = hoy.year, (hoy.month - 1) // 3 + 1
    for _ in range(8):
        periodo = f"{anio}_T{trim}"
        if publicado(periodo):
            return periodo
        anio, trim = (anio, trim - 1) if trim > 1 else (anio - 1, 4)
    return None


# ── Estado (qué trimestres ya se procesaron) ──────────────────────────────────

def leer_estado() -> dict:
    if ESTADO.exists():
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    return {"procesados": []}


def guardar_estado(estado: dict):
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def marcar_procesado(periodo: str):
    estado = leer_estado()
    if periodo not in estado["procesados"]:
        estado["procesados"].append(periodo)
    ahora = ahora_cdmx().isoformat(timespec="seconds")      # hora CDMX (en GitHub el reloj está en UTC)
    estado["ultimo"] = periodo
    estado["fecha_ultimo"] = ahora
    estado.setdefault("generadas", {})[periodo] = ahora
    guardar_estado(estado)


def borrar_ficha(periodo: str) -> list[str]:
    """Borra la ficha (.txt y .docx) de un trimestre y lo quita de los procesados.
    No toca "ultimo" (el robot sigue esperando el trimestre siguiente) ni los indicadores en datos/."""
    borrados = []
    for ext in (".txt", ".docx"):
        ruta = FICHAS / f"ficha_{periodo}{ext}"
        if ruta.exists():
            ruta.unlink()
            borrados.append(ruta.name)
    estado = leer_estado()
    if periodo in estado["procesados"]:
        estado["procesados"].remove(periodo)
    estado.get("generadas", {}).pop(periodo, None)
    guardar_estado(estado)
    return borrados


# ── Revisión y series ─────────────────────────────────────────────────────────

def revisar(ind: dict):
    """Detiene el proceso si los datos no tienen sentido (mejor no mandar nada que mandar algo mal)."""
    problemas = []
    if len(ind["entidades"]) != 32:
        problemas.append(f"se esperaban 32 entidades y hay {len(ind['entidades'])}")
    for grupo in ("total", "hombres", "mujeres"):
        valores = ind["jalisco"][grupo]
        if not 0 < valores["td"] < 20 or not 20 < valores["tpea"] < 90:
            problemas.append(f"valores fuera de rango para Jalisco ({grupo}): {valores}")
    oc = ind["jalisco"]["ocupacion"]
    if abs(oc["formal"] + oc["informal"] - oc["total"]) > 0.001 * oc["total"]:
        problemas.append(f"formal + informal no suma el total de ocupados: {oc}")
    if oc["sector_no_especificado"] > 0.05 * oc["total"]:
        problemas.append(f"demasiados ocupados sin sector de actividad: {oc}")
    if problemas:
        raise RuntimeError("Revisión de datos falló: " + "; ".join(problemas))


def _upsert(ruta: Path, fila: dict):
    df = pd.read_csv(ruta) if ruta.exists() else pd.DataFrame(columns=list(fila))
    df = df[df["periodo"] != fila["periodo"]]
    df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True).sort_values("periodo")
    df.to_csv(ruta, index=False)


def actualizar_series(ind: dict):
    j = ind["jalisco"]["total"]
    anio, trim = map(int, ind["periodo"].split("_T"))
    base = {"periodo": ind["periodo"], "anio": anio, "trimestre": trim}
    _upsert(SERIE_TD, {**base, "td": round(j["td"], 2)})
    _upsert(SERIE_INDICADORES, {
        **base, "pob_ocupada": j["ocupada"], "pob_desocupada": j["desocupada"],
        "tpea": round(j["tpea"], 2), "td": round(j["td"], 2),
        "subocupacion": round(j["subocupacion"], 2), "til1": round(j["til1"], 2),
    })


# ── Correo ────────────────────────────────────────────────────────────────────

def _valor(config, clave, env):
    """Primero la variable de entorno (GitHub Actions), luego config.ini."""
    return os.environ.get(env) or config.get("email", clave, fallback="")


def enviar_correo(config, contexto, adjuntos: list[Path], extra=()):
    usuario = _valor(config, "usuario", "SMTP_USUARIO")
    destinatarios = [d.strip() for d in _valor(config, "destinatarios", "DESTINATARIOS").split(",") if d.strip()]
    destinatarios += [d for d in extra if d.lower() not in {x.lower() for x in destinatarios}]
    if not usuario or not destinatarios:
        log.info("  Correo no configurado: se omite el envío.")
        return

    c = contexto
    (H, _), (M, _) = c.sexo["hombres"], c.sexo["mujeres"]
    msg = EmailMessage()
    msg["From"] = _valor(config, "remitente", "SMTP_REMITENTE") or usuario
    msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = f"[ENOE Jalisco] Ficha de Tasa de Desocupación — {c.act}"
    msg.set_content(
        f"Se adjunta la ficha informativa del mercado laboral de Jalisco, {c.act}.\n\n"
        f"Resumen:\n"
        f"  · TD: {c.J['td']:.2f}% (año anterior {c.Ja['td']:.2f}%), lugar {c.rank} de {c.n} entidades\n"
        f"  · TD hombres: {H['td']:.2f}%   ·   TD mujeres: {M['td']:.2f}%\n"
        f"  · TPEA: {c.J['tpea']:.1f}%   ·   TIL1: {c.J['til1']:.1f}%\n"
        f"  · Población ocupada: {c.ocupada_resumen}\n\n"
        f"Archivos: ficha en texto (.txt) y en Word (.docx).\n\n"
        f"Generado automáticamente a partir de los microdatos de la ENOE (INEGI).\n"
        f"Proyecto de Aplicación Profesional — Economía, ITESO"
    )
    for ruta in adjuntos:
        msg.add_attachment(ruta.read_bytes(), maintype="application",
                           subtype="octet-stream", filename=ruta.name)

    host = _valor(config, "smtp_host", "SMTP_HOST") or "smtp.gmail.com"
    puerto = int(_valor(config, "smtp_port", "SMTP_PORT") or 587)
    with smtplib.SMTP(host, puerto, timeout=60) as srv:
        srv.starttls()
        srv.login(usuario, _valor(config, "password", "SMTP_PASSWORD"))
        srv.send_message(msg)
    log.info(f"  Correo enviado a: {', '.join(destinatarios)}")


# ── Pipeline ──────────────────────────────────────────────────────────────────

def ejecutar(periodo: str, config, sin_email=False, correos_extra=()) -> tuple[Path, Path]:
    log.info(f"━━ Pipeline ENOE Jalisco — {periodo} ━━")

    log.info("→ 1/5 Calculando indicadores desde los microdatos...")
    act = calcular(periodo, DATOS)
    ant = calcular(periodo_anterior(periodo), DATOS)
    dic = calcular(cierre_anio_anterior(periodo), DATOS)
    prev = calcular(trimestre_previo(periodo), DATOS)
    for ind in (act, ant, dic, prev):
        revisar(ind)
    log.info(f"  Jalisco TD {act['jalisco']['total']['td']:.2f}% · año anterior {ant['jalisco']['total']['td']:.2f}%")

    log.info("→ 2/5 Actualizando series históricas...")
    actualizar_series(ant)
    actualizar_series(act)

    log.info("→ 3/5 Generando ficha...")
    contexto = preparar(act, ant, dic, prev)
    FICHAS.mkdir(exist_ok=True)
    txt, docx = FICHAS / f"ficha_{periodo}.txt", FICHAS / f"ficha_{periodo}.docx"
    generar_txt(contexto, txt)
    generar_docx(contexto, docx)
    log.info(f"  {txt.name} · {docx.name}")

    if sin_email:
        log.info("→ 4/5 Correo omitido (--sin-email).")
    else:
        log.info("→ 4/5 Enviando correo...")
        enviar_correo(config, contexto, [txt, docx], extra=correos_extra)

    log.info("→ 5/5 Registrando período como procesado.")
    marcar_procesado(periodo)
    log.info("✅ Listo.")
    return txt, docx


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pipeline trimestral ENOE Jalisco")
    ap.add_argument("--periodo", help="AAAA_T# (ej. 2026_T3). Si se omite, se detecta.")
    ap.add_argument("--forzar", action="store_true", help="Rehacer aunque ya esté procesado")
    ap.add_argument("--sin-email", action="store_true", help="No enviar correo")
    args = ap.parse_args()

    config = configparser.ConfigParser()
    config.read(CONFIG, encoding="utf-8")

    periodo = args.periodo or detectar_periodo()
    if not periodo:
        raise SystemExit("No se encontró ningún trimestre publicado. Usa --periodo.")
    if periodo in leer_estado()["procesados"] and not args.forzar:
        log.info(f"{periodo} ya fue procesado. Usa --forzar para rehacerlo.")
        raise SystemExit(0)

    ejecutar(periodo, config, sin_email=args.sin_email)
