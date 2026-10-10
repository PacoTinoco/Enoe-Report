"""
construir_sitio.py — Datos del dashboard web (GitHub Pages)
============================================================
Junta en docs/data.json todo lo que muestra el dashboard (docs/index.html) y copia
las fichas a docs/fichas/. El robot lo corre después de cada ejecución; GitHub Pages
publica la carpeta docs/ automáticamente.

Uso:  python construir_sitio.py

Es idempotente: si los datos no cambiaron, los archivos quedan idénticos (no hay commit).
"""

import csv
import json
import shutil
from pathlib import Path

from calcular_indicadores import SECTORES

BASE   = Path(__file__).parent
DATOS  = BASE / "datos"
FICHAS = BASE / "fichas"
DOCS   = BASE / "docs"

INDICADORES = ("td", "tpea", "til1", "subocupacion")


def leer_json(ruta: Path, defecto=None):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else defecto


def leer_csv(ruta: Path, columnas) -> list[dict]:
    if not ruta.exists():
        return []
    with ruta.open(encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    salida = []
    for fila in filas:
        registro = {"periodo": fila["periodo"]}
        for col in columnas:
            if fila.get(col) not in (None, ""):
                registro[col] = round(float(fila[col]), 2)
        salida.append(registro)
    return sorted(salida, key=lambda r: r["periodo"])


def periodo_compacto(d: dict) -> dict:
    """Lo que usa el dashboard de un trimestre (sin campos que no se muestran)."""
    j = d["jalisco"]
    redondear = lambda g: {k: round(v, 2) if isinstance(v, float) else v for k, v in g.items()}
    return {
        "jalisco": {s: redondear(j[s]) for s in ("total", "hombres", "mujeres")},
        "ocupacion": j.get("ocupacion"),
        "nacional": redondear(d["nacional"]),
        "entidades": [{"nombre": e["nombre"], **{k: round(e[k], 2) for k in INDICADORES}}
                      for e in d["entidades"]],
    }


def sincronizar_fichas() -> list[dict]:
    """Copia fichas/ a docs/fichas/ (y borra las que ya no existen)."""
    destino = DOCS / "fichas"
    destino.mkdir(parents=True, exist_ok=True)
    origen = {p.name for p in FICHAS.glob("ficha_*.*")} if FICHAS.exists() else set()
    for viejo in destino.glob("ficha_*.*"):
        if viejo.name not in origen:
            viejo.unlink()
    for nombre in origen:
        src, dst = FICHAS / nombre, destino / nombre
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            shutil.copyfile(src, dst)

    generadas = leer_json(BASE / "procesados.json", {}).get("generadas", {})
    fichas = []
    for txt in sorted(FICHAS.glob("ficha_*.txt"), reverse=True) if FICHAS.exists() else []:
        per = txt.stem.replace("ficha_", "")
        docx = txt.with_suffix(".docx")
        fichas.append({
            "periodo": per,
            "txt": f"fichas/{txt.name}",
            "docx": f"fichas/{docx.name}" if docx.exists() else None,
            "generada": generadas.get(per),
        })
    return fichas


def construir() -> Path:
    DOCS.mkdir(exist_ok=True)
    (DOCS / ".nojekyll").touch()

    periodos = {}
    for ruta in sorted(DATOS.glob("indicadores_*.json")):
        d = leer_json(ruta)
        if d and "ocupacion" in d.get("jalisco", {}):
            periodos[d["periodo"]] = periodo_compacto(d)

    data = {
        "periodos": periodos,
        "sectores": {str(k): v for k, v in SECTORES.items()},
        "serie_td": leer_csv(BASE / "serie_bie_jalisco.csv", ["td"]),
        "serie_indicadores": leer_csv(BASE / "serie_indicadores_jalisco.csv", INDICADORES + ("pob_ocupada",)),
        "calendario": leer_json(BASE / "calendario_enoe.json", []),
        "fichas": sincronizar_fichas(),
        "historial": leer_json(BASE / "historial_robot.json", []),
    }
    salida = DOCS / "data.json"
    texto = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if not salida.exists() or salida.read_text(encoding="utf-8") != texto:
        salida.write_text(texto, encoding="utf-8")
    return salida


if __name__ == "__main__":
    ruta = construir()
    print(f"✓ {ruta.relative_to(BASE)} ({ruta.stat().st_size / 1024:.0f} KB)")
