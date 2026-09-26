"""
calendario.py
=============
Lee el calendario oficial de INEGI (feed .ics) y extrae las fechas de publicación
de la ENOE trimestral (la que trae datos por entidad).

Uso:
    python calendario.py          # muestra las próximas publicaciones
"""

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

URL_ICS = "https://www.inegi.org.mx/contenidos/saladeprensa/doc/inegi.ics"
ARCHIVO = Path(__file__).parent / "calendario_enoe.json"

# México eliminó el horario de verano en 2022: la Ciudad de México es UTC−6 todo el año.
# (El .ics de INEGI todavía declara reglas de horario de verano; por eso no se usan.)
CDMX = timezone(timedelta(hours=-6), "CDMX")


def ahora_cdmx() -> datetime:
    return datetime.now(CDMX)


def periodo_de_publicacion(fecha: date) -> str:
    """Trimestre que se publica en esa fecha: el último trimestre ya terminado."""
    trim_actual = (fecha.month - 1) // 3 + 1
    if trim_actual == 1:
        return f"{fecha.year - 1}_T4"
    return f"{fecha.year}_T{trim_actual - 1}"


def descargar_publicaciones() -> list[dict]:
    """Publicaciones de la ENOE trimestral que aparecen en el calendario de INEGI."""
    r = requests.get(URL_ICS, timeout=60)
    r.raise_for_status()
    texto = r.content.decode("utf-8", errors="replace")
    texto = re.sub(r"\r?\n[ \t]", "", texto)            # une las líneas partidas del .ics

    publicaciones = []
    for evento in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", texto, re.S):
        resumen = re.search(r"^SUMMARY[^:]*:(.*)$", evento, re.M)
        inicio = re.search(r"^DTSTART[^:]*:(\d{8}T\d{6})", evento, re.M)
        if not resumen or not inicio:
            continue
        resumen = resumen.group(1)
        # La trimestral es "ENOE ... Cifras definitivas"; la mensual dice "Indicadores de Ocupación y Empleo"
        if "Ocupación y Empleo (ENOE)" not in resumen or "Indicadores de Ocupación" in resumen:
            continue
        fecha = datetime.strptime(inicio.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=CDMX)
        publicaciones.append({
            "periodo": periodo_de_publicacion(fecha.date()),
            "fecha": fecha.isoformat(),
        })
    return sorted(publicaciones, key=lambda p: p["fecha"])


def actualizar() -> tuple[list[dict], list[str]]:
    """
    Descarga el calendario, lo compara con la versión guardada y la reemplaza.
    Devuelve (publicaciones, avisos) — avisos describe fechas nuevas o cambiadas.
    """
    nuevas = descargar_publicaciones()
    anteriores = {}
    if ARCHIVO.exists():
        anteriores = {p["periodo"]: p["fecha"] for p in json.loads(ARCHIVO.read_text(encoding="utf-8"))}

    avisos = []
    for p in nuevas:
        antes = anteriores.get(p["periodo"])
        if antes and antes != p["fecha"]:
            avisos.append(f"INEGI cambió la fecha de {p['periodo']}: {antes[:16]} → {p['fecha'][:16]}")
    if not any(datetime.fromisoformat(p["fecha"]) > ahora_cdmx() for p in nuevas):
        avisos.append("El calendario de INEGI ya no tiene fechas futuras de la ENOE trimestral.")

    ARCHIVO.write_text(json.dumps(nuevas, ensure_ascii=False, indent=2), encoding="utf-8")
    return nuevas, avisos


def guardadas() -> list[dict]:
    """Publicaciones guardadas en calendario_enoe.json (sin descargar)."""
    if not ARCHIVO.exists():
        return []
    return json.loads(ARCHIVO.read_text(encoding="utf-8"))


def proxima(publicaciones: list[dict]) -> dict | None:
    futuras = [p for p in publicaciones if datetime.fromisoformat(p["fecha"]) > ahora_cdmx()]
    return futuras[0] if futuras else None


if __name__ == "__main__":
    pubs, avisos = actualizar()
    print("ENOE trimestral — publicaciones en el calendario de INEGI:")
    for p in pubs:
        marca = "  ← próxima" if p == proxima(pubs) else ""
        print(f"  {p['fecha'][:16].replace('T', ' ')}  {p['periodo']}{marca}")
    for a in avisos:
        print(f"⚠ {a}")
