"""
robot.py
========
Vigila la publicación de la ENOE y genera + envía la ficha en cuanto INEGI publica.
Está pensado para correr todos los días a las 06:00 (GitHub Actions), pero se puede
correr a mano igual.

Lógica de cada día:
    1. Actualiza el calendario de INEGI y avisa si cambió una fecha.
    2. Busca el trimestre pendiente (el siguiente al último procesado).
    3. Si sus microdatos ya están publicados → genera la ficha y manda el correo.
    4. Si hoy es día de publicación según el calendario pero aún no salen,
       revisa cada 5 minutos hasta las 10:00. Si a esa hora no han salido,
       termina con error (GitHub le avisa por correo al administrador).
    5. Si no es día de publicación, termina (tarda unos segundos).

Aunque INEGI mueva una fecha sin avisar, el paso 3 detecta la publicación
a la mañana siguiente.

Uso:
    python robot.py                          # revisión normal
    python robot.py --periodo 2026_T3        # forzar un trimestre específico
    python robot.py --hoy 2026-11-25         # simular otra fecha (pruebas)
    python robot.py --borrar 2026_T2         # borrar la ficha de un trimestre
"""

import argparse
import configparser
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import calendario
from calcular_indicadores import publicado
from pipeline_trimestral import CONFIG, borrar_ficha, detectar_periodo, ejecutar, leer_estado

HORA_LIMITE = 10          # hasta qué hora (CDMX) esperar el día de publicación
ESPERA_SEG  = 5 * 60      # cada cuánto revisar
HISTORIAL   = Path(__file__).parent / "historial_robot.json"   # lo que encontró el robot en cada ejecución
MAX_HISTORIAL = 90
MENSAJES: list[str] = []


def siguiente(periodo: str) -> str:
    anio, trim = map(int, periodo.split("_T"))
    return f"{anio + 1}_T1" if trim == 4 else f"{anio}_T{trim + 1}"


def resumen(texto: str):
    """Imprime y, si corre en GitHub Actions, lo agrega al resumen de la ejecución."""
    print(texto)
    MENSAJES.append(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto + "\n\n")


def _limpiar(texto: str) -> str:
    """Quita emojis y símbolos del inicio ('✅ Ficha...' → 'Ficha...')."""
    return re.sub(r"^[^\w¿¡(]+", "", texto).strip()


def _tipo(mensajes: list[str], error: str | None) -> str:
    if error:
        return "error"
    texto = " ".join(mensajes)
    if "generada" in texto:
        return "generada"
    if "borrada" in texto or "No había ficha" in texto:
        return "borrada"
    if "ya fue procesado" in texto:
        return "ya_procesada"
    return "sin_publicacion"


def registrar_historial(error: str | None = None):
    """Agrega esta ejecución a historial_robot.json (solo en GitHub Actions)."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    try:
        historial = json.loads(HISTORIAL.read_text(encoding="utf-8")) if HISTORIAL.exists() else []
        repo, corrida = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_RUN_ID", "")
        detalle = [_limpiar(m) for m in MENSAJES] + ([_limpiar(error)] if error else [])
        historial.insert(0, {
            "id": int(corrida) if corrida.isdigit() else None,
            "fecha": calendario.ahora_cdmx().isoformat(timespec="seconds"),
            "evento": os.environ.get("GITHUB_EVENT_NAME", ""),
            "tipo": _tipo(MENSAJES, error),
            "detalle": " · ".join(d for d in detalle if d)[:400],
            "url": f"https://github.com/{repo}/actions/runs/{corrida}" if repo and corrida else "",
        })
        HISTORIAL.write_text(json.dumps(historial[:MAX_HISTORIAL], ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:                       # el historial nunca debe tumbar al robot
        print(f"(No se pudo guardar el historial: {e})")


def main():
    error = None
    try:
        _main()
    except SystemExit as e:
        if e.code not in (None, 0):
            error = str(e.code)
        raise
    finally:
        registrar_historial(error)


def _main():
    ap = argparse.ArgumentParser(description="Robot ENOE Jalisco")
    ap.add_argument("--periodo", help="AAAA_T# — procesar este trimestre")
    ap.add_argument("--forzar", action="store_true", help="Rehacer aunque ya esté procesado")
    ap.add_argument("--sin-email", action="store_true", help="No enviar correo")
    ap.add_argument("--hoy", help="AAAA-MM-DD — simular la fecha (para pruebas)")
    ap.add_argument("--borrar", help="AAAA_T# — borrar la ficha de este trimestre y terminar")
    ap.add_argument("--correo", help="Correo(s) adicional(es) para esta ficha, separados por coma")
    args = ap.parse_args()

    for p in (args.periodo, args.borrar):
        if p and not re.fullmatch(r"\d{4}_T[1-4]", p):
            sys.exit(f"Período inválido: {p!r} (formato AAAA_T#)")
    correos = [c.strip() for c in (args.correo or "").split(",") if c.strip()]
    for c in correos:
        if not re.fullmatch(r"[^@\s,]+@[^@\s,]+\.[^@\s,]+", c):
            sys.exit(f"Correo inválido: {c!r}")
    if len(correos) > 5:
        sys.exit("Máximo 5 correos adicionales.")

    if args.borrar:
        borrados = borrar_ficha(args.borrar)
        resumen(f"🗑️ Ficha {args.borrar} borrada: {', '.join(borrados)}" if borrados
                else f"No había ficha de {args.borrar}.")
        return
    hoy = date.fromisoformat(args.hoy) if args.hoy else calendario.ahora_cdmx().date()
    config = configparser.ConfigParser()
    config.read(CONFIG, encoding="utf-8")

    # 1. Calendario
    try:
        publicaciones, avisos = calendario.actualizar()
    except Exception as e:                      # sin calendario el robot sigue funcionando
        publicaciones, avisos = calendario.guardadas(), [f"No se pudo descargar el calendario: {e}"]
    for aviso in avisos:
        resumen(f"⚠️ {aviso}")
    del_dia = next((p for p in publicaciones if p["fecha"][:10] == hoy.isoformat()), None)

    # 2. Trimestre a revisar
    estado = leer_estado()
    if args.periodo:
        periodo = args.periodo
    elif del_dia:
        periodo = del_dia["periodo"]
    elif estado.get("ultimo"):
        periodo = siguiente(estado["ultimo"])
    else:
        periodo = detectar_periodo()

    if periodo in estado["procesados"] and not args.forzar:
        prox = calendario.proxima(publicaciones)
        resumen(f"✔ {periodo} ya fue procesado. Próxima publicación: "
                + (f"{prox['periodo']} el {prox['fecha'][:10]} 06:00" if prox else "sin fecha en el calendario"))
        return

    # 3. ¿Ya está publicado?
    if publicado(periodo):
        ejecutar(periodo, config, sin_email=args.sin_email, correos_extra=correos)
        resumen(f"✅ Ficha {periodo} generada" + ("" if args.sin_email else " y enviada") + ".")
        return

    if args.periodo:
        sys.exit(f"Los microdatos de {periodo} todavía no están publicados.")

    # 4. Día de publicación: esperar
    if del_dia:
        resumen(f"📅 Hoy INEGI publica {periodo}. Esperando los microdatos (hasta las {HORA_LIMITE}:00)...")
        while calendario.ahora_cdmx().hour < HORA_LIMITE:
            time.sleep(ESPERA_SEG)
            if publicado(periodo):
                ejecutar(periodo, config, sin_email=args.sin_email, correos_extra=correos)
                resumen(f"✅ Ficha {periodo} generada" + ("" if args.sin_email else " y enviada") + ".")
                return
        sys.exit(f"❌ Hoy era día de publicación de {periodo} y a las {HORA_LIMITE}:00 "
                 "los microdatos no estaban disponibles. Revisar el sitio de INEGI.")

    # 5. Día normal
    prox = calendario.proxima(publicaciones)
    resumen(f"Sin publicación hoy ({hoy}). Pendiente: {periodo}. Próxima publicación: "
            + (f"{prox['periodo']} el {prox['fecha'][:10]} 06:00" if prox else "sin fecha en el calendario"))


if __name__ == "__main__":
    main()
