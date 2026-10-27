"""
calcular_indicadores.py
=======================
Calcula los indicadores laborales de la ENOE a partir de los microdatos
(datos abiertos de INEGI): Jalisco total / hombres / mujeres, total nacional
y las 32 entidades.

Uso como script:
    python calcular_indicadores.py --periodo 2026_T2

Uso como módulo:
    from calcular_indicadores import calcular
    ind = calcular("2026_T2")

Metodología (la misma que usa INEGI para sus tabulados):
    · Tabla SDEM (sociodemográfica) del trimestre.
    · Entrevistas completas (r_def = 0), residentes habituales (c_res = 1 o 3),
      población de 15 años y más (eda 15–98).
    · Ponderador: factor de expansión trimestral (fac_tri).
    · TD   = desocupados (clase2 = 2) / PEA (clase1 = 1)
    · TPEA = PEA / población de 15 años y más
    · TIL1 = ocupados en informalidad (emp_ppal = 1) / ocupados (clase2 = 1)
    · Subocupación = ocupados subocupados (sub_o = 1) / ocupados
    · Población ocupada de Jalisco en personas: total, formal/informal (emp_ppal),
      por sexo y por sector de actividad (rama_est2, 11 sectores de INEGI)
"""

import argparse
import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd
import requests

URL_MICRODATOS = (
    "https://www.inegi.org.mx/contenidos/programas/enoe/15ymas/datosabiertos"
    "/{anio}/conjunto_de_datos_enoe_{anio}_{trim}t_csv.zip"
)

JALISCO = 14

ENTIDADES = {
    1: "Aguascalientes", 2: "Baja California", 3: "Baja California Sur",
    4: "Campeche", 5: "Coahuila", 6: "Colima", 7: "Chiapas", 8: "Chihuahua",
    9: "Ciudad de México", 10: "Durango", 11: "Guanajuato", 12: "Guerrero",
    13: "Hidalgo", 14: "Jalisco", 15: "Estado de México", 16: "Michoacán",
    17: "Morelos", 18: "Nayarit", 19: "Nuevo León", 20: "Oaxaca", 21: "Puebla",
    22: "Querétaro", 23: "Quintana Roo", 24: "San Luis Potosí", 25: "Sinaloa",
    26: "Sonora", 27: "Tabasco", 28: "Tamaulipas", 29: "Tlaxcala",
    30: "Veracruz", 31: "Yucatán", 32: "Zacatecas",
}

# Región Occidente / Centro-Bajío usada en la ficha
REGION = [1, 6, 11, 14, 16, 18, 24, 32]

COLUMNAS = ["r_def", "c_res", "eda", "sex", "cve_ent", "fac_tri",
            "clase1", "clase2", "emp_ppal", "sub_o", "rama_est2"]

# Sectores de actividad económica (catálogo rama_est2 de la ENOE), con nombres cortos
SECTORES = {
    1: "Agropecuario",
    2: "Ind. extractiva y electricidad",
    3: "Manufactura",
    4: "Construcción",
    5: "Comercio",
    6: "Restaurantes y alojamiento",
    7: "Transportes y comunicaciones",
    8: "Serv. profesionales y financ.",
    9: "Servicios sociales",
    10: "Servicios diversos",
    11: "Gobierno y org. internac.",
}


# ── Períodos y descarga ───────────────────────────────────────────────────────

def _partes(periodo: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{4})_T([1-4])", periodo)
    if not m:
        raise ValueError(f"Período inválido: {periodo!r} (formato AAAA_T#)")
    return int(m.group(1)), int(m.group(2))


def url_microdatos(periodo: str) -> str:
    anio, trim = _partes(periodo)
    return URL_MICRODATOS.format(anio=anio, trim=trim)


def publicado(periodo: str) -> bool:
    """
    True si INEGI ya publicó los microdatos del período.
    INEGI no responde bien a HEAD (devuelve 200 con una página HTML aunque el ZIP exista),
    y para archivos inexistentes también responde 200 con HTML. Por eso se pide con GET
    solo los primeros bytes (Range) y se revisa que empiecen con la firma de un ZIP ("PK").
    """
    try:
        with requests.get(url_microdatos(periodo), headers={"Range": "bytes=0-3"},
                          timeout=30, allow_redirects=True, stream=True) as r:
            inicio = next(r.iter_content(chunk_size=4), b"")
            tipo = r.headers.get("Content-Type", "").lower()
            return r.status_code in (200, 206) and "html" not in tipo and inicio[:2] == b"PK"
    except requests.RequestException:
        return False


def descargar_microdatos(periodo: str, carpeta: Path) -> Path:
    """Descarga el ZIP de microdatos (si no está ya en la carpeta)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"enoe_{periodo}.zip"
    if ruta.exists() and zipfile.is_zipfile(ruta):
        return ruta
    print(f"  ↓ Descargando microdatos {periodo}...")
    r = requests.get(url_microdatos(periodo), timeout=300)
    r.raise_for_status()
    if not r.content.startswith(b"PK"):   # INEGI devuelve HTML si el archivo no existe
        raise RuntimeError(f"Los microdatos de {periodo} aún no están publicados.")
    ruta.write_bytes(r.content)
    return ruta


def leer_sdem(ruta_zip: Path) -> pd.DataFrame:
    """Lee solo las columnas necesarias de la tabla SDEM dentro del ZIP."""
    with zipfile.ZipFile(ruta_zip) as z:
        nombre = next(
            n for n in z.namelist()
            if re.search(r"conjunto_de_datos_sdem_.*\.csv$", n) and "/conjunto_de_datos/" in n
        )
        with z.open(nombre) as f:
            df = pd.read_csv(io.TextIOWrapper(f, encoding="latin-1"),
                             usecols=lambda c: c.lower() in COLUMNAS + ["ent"],
                             low_memory=False)
    # La clave de entidad se llama "ent" hasta 2025 y "cve_ent" desde 2026
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"ent": "cve_ent"})
    df = df.apply(pd.to_numeric, errors="coerce")
    filtro = (df.r_def == 0) & df.c_res.isin([1, 3]) & df.eda.between(15, 98)
    return df[filtro]


# ── Cálculo ───────────────────────────────────────────────────────────────────

def _tasas(df: pd.DataFrame) -> dict:
    w = df.fac_tri
    pob15     = w.sum()
    pea       = w[df.clase1 == 1].sum()
    ocupada   = w[df.clase2 == 1].sum()
    desocupada = w[df.clase2 == 2].sum()
    informal  = w[(df.clase2 == 1) & (df.emp_ppal == 1)].sum()
    subocup   = w[(df.clase2 == 1) & (df.sub_o == 1)].sum()
    return {
        "td":           round(100 * desocupada / pea, 4),
        "tpea":         round(100 * pea / pob15, 4),
        "til1":         round(100 * informal / ocupada, 4),
        "subocupacion": round(100 * subocup / ocupada, 4),
        "pob15":        int(pob15),
        "pea":          int(pea),
        "ocupada":      int(ocupada),
        "desocupada":   int(desocupada),
    }


def _ocupacion(df: pd.DataFrame) -> dict:
    """Población ocupada en número de personas, desagregada."""
    oc = df[df.clase2 == 1]
    w = oc.fac_tri
    sectores = {str(k): int(w[oc.rama_est2 == k].sum()) for k in SECTORES}
    total = int(w.sum())
    return {
        "total":    total,
        "formal":   int(w[oc.emp_ppal == 2].sum()),
        "informal": int(w[oc.emp_ppal == 1].sum()),
        "hombres":  int(w[oc.sex == 1].sum()),
        "mujeres":  int(w[oc.sex == 2].sum()),
        "sectores": sectores,
        "sector_no_especificado": total - sum(sectores.values()),
    }


def calcular(periodo: str, carpeta: str | Path = "datos") -> dict:
    """
    Devuelve (y guarda en datos/indicadores_AAAA_T#.json):
        {
          "periodo": "2026_T2",
          "jalisco":  {"total": {...}, "hombres": {...}, "mujeres": {...}},
          "nacional": {...},
          "entidades": [{"cve": 1, "nombre": "Aguascalientes", "td": ..., ...}, ...]
        }
    """
    carpeta = Path(carpeta)
    cache = carpeta / f"indicadores_{periodo}.json"
    if cache.exists():
        guardado = json.loads(cache.read_text(encoding="utf-8"))
        if "ocupacion" in guardado["jalisco"]:      # los archivos viejos no la traen: se recalcula
            return guardado

    df = leer_sdem(descargar_microdatos(periodo, carpeta))
    jal = df[df.cve_ent == JALISCO]

    resultado = {
        "periodo": periodo,
        "jalisco": {
            "total":   _tasas(jal),
            "hombres": _tasas(jal[jal.sex == 1]),
            "mujeres": _tasas(jal[jal.sex == 2]),
            "ocupacion": _ocupacion(jal),
        },
        "nacional": _tasas(df),
        "entidades": [
            {"cve": int(cve), "nombre": ENTIDADES[int(cve)], **_tasas(grupo)}
            for cve, grupo in df.groupby("cve_ent")
        ],
    }
    cache.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    return resultado


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Indicadores ENOE desde microdatos")
    ap.add_argument("--periodo", required=True, help="AAAA_T# (ej. 2026_T2)")
    ap.add_argument("--carpeta", default="datos")
    args = ap.parse_args()

    r = calcular(args.periodo, args.carpeta)
    j = r["jalisco"]
    print(f"\nJalisco {args.periodo}   Total   Hombres  Mujeres")
    for k in ["td", "tpea", "til1", "subocupacion"]:
        print(f"  {k:<14} {j['total'][k]:6.2f}  {j['hombres'][k]:6.2f}  {j['mujeres'][k]:6.2f}")
    print(f"  Nacional TD: {r['nacional']['td']:.2f}")
