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
"""

import argparse
import configparser
import os
import re
import sys
import time
from datetime import date, datetime

import calendario
from calcular_indicadores import publicado
from pipeline_trimestral import CONFIG, detectar_periodo, ejecutar, leer_estado

HORA_LIMITE = 10          # hasta qué hora (CDMX) esperar el día de publicación
ESPERA_SEG  = 5 * 60      # cada cuánto revisar


def siguiente(periodo: str) -> str:
    anio, trim = map(int, periodo.split("_T"))
    return f"{anio + 1}_T1" if trim == 4 else f"{anio}_T{trim + 1}"


def resumen(texto: str):
    """Imprime y, si corre en GitHub Actions, lo agrega al resumen de la ejecución."""
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto + "\n\n")


def main():
    ap = argparse.ArgumentParser(description="Robot ENOE Jalisco")
    ap.add_argument("--periodo", help="AAAA_T# — procesar este trimestre")
    ap.add_argument("--forzar", action="store_true", help="Rehacer aunque ya esté procesado")
    ap.add_argument("--sin-email", action="store_true", help="No enviar correo")
    ap.add_argument("--hoy", help="AAAA-MM-DD — simular la fecha (para pruebas)")
    args = ap.parse_args()

    if args.periodo and not re.fullmatch(r"\d{4}_T[1-4]", args.periodo):
        sys.exit(f"Período inválido: {args.periodo!r} (formato AAAA_T#)")
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
        ejecutar(periodo, config, sin_email=args.sin_email)
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
                ejecutar(periodo, config, sin_email=args.sin_email)
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
