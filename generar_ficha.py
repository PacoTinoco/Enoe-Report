"""
generar_ficha.py
================
Genera la ficha informativa trimestral (.txt y .docx) a partir de los
indicadores de calcular_indicadores.py.

Todos los textos y cifras se arman una sola vez en `preparar()` y después se
escriben en los dos formatos, así el .txt y el .docx siempre dicen lo mismo.

Uso:
    python generar_ficha.py --periodo 2026_T2
"""

import argparse
import re
import textwrap
from pathlib import Path
from types import SimpleNamespace

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from calcular_indicadores import JALISCO, REGION, calcular

REGLA = "─" * 60
ORDINAL = {1: "1°", 2: "2°", 3: "3°", 4: "4°"}
NOMBRES = {
    "td":           "Tasa de Desocupación (TD)",
    "tpea":         "Tasa de Participación Económica (TPEA)",
    "til1":         "Tasa de Informalidad Laboral (TIL1)",
    "subocupacion": "Tasa de Subocupación",
}
CORTOS = {"td": "TD", "tpea": "TPEA", "til1": "TIL1", "subocupacion": "Subocupación"}
DECIMALES = {"td": 2, "tpea": 1, "til1": 1, "subocupacion": 1}


# ── Formato de números ────────────────────────────────────────────────────────
# Las diferencias se calculan con los valores ya redondeados para que cada
# tabla sea consistente a simple vista (lo que se lee es lo que se resta).

def r(v, k):
    return round(v, DECIMALES[k])

def pct(v, k):
    return f"{r(v, k):.{DECIMALES[k]}f}%"

def dif(a, b, k):
    return round(r(a, k) - r(b, k), DECIMALES[k])

def signo(v, dec=2):
    return f"{'−' if v < 0 else '+'}{abs(v):.{dec}f}"


# ── Contenido de la ficha ─────────────────────────────────────────────────────

def preparar(act: dict, ant: dict) -> SimpleNamespace:
    """Arma todas las cifras y frases de la ficha."""
    anio, trim = map(int, re.fullmatch(r"(\d{4})_T(\d)", act["periodo"]).groups())
    c = SimpleNamespace()
    c.anio, c.trim = anio, trim
    c.act, c.ant = f"T{trim} {anio}", f"T{trim} {anio - 1}"
    c.titulo = f"Tasa de Desocupación — Jalisco. {ORDINAL[trim]} Trimestre {anio}"

    J, Ja = act["jalisco"]["total"], ant["jalisco"]["total"]
    N, Na = act["nacional"], ant["nacional"]
    c.J, c.Ja, c.N = J, Ja, N
    c.sexo = {s: (act["jalisco"][s], ant["jalisco"][s]) for s in ("hombres", "mujeres")}

    # ── Análisis anual ────────────────────────────────────────────────────
    var = dif(J["td"], Ja["td"], "td")
    rel = abs(var) / r(Ja["td"], "td") * 100
    dif_nac = dif(J["td"], N["td"], "td")
    if var < 0:
        cambio, rel_txt = f"disminución de {abs(var):.2f} puntos porcentuales", "una reducción relativa"
    elif var > 0:
        cambio, rel_txt = f"aumento de {var:.2f} puntos porcentuales", "un aumento relativo"
    else:
        cambio, rel_txt = "variación nula", "una variación relativa"
    c.p_anual = [
        ("La Tasa de Desocupación (TD) de Jalisco en el ", 0),
        (f"{ORDINAL[trim]} Trimestre {anio}", 1), (" fue de ", 0), (pct(J["td"], "td"), 1),
        (", lo que representa una ", 0), (cambio, 1),
        (" respecto al mismo trimestre del año anterior, que registró ", 0),
        (pct(Ja["td"], "td"), 1), (f" ({c.ant}). Esto equivale a {rel_txt} del ", 0),
        (f"{rel:.1f}%", 1), (" anual.", 0),
    ]
    c.p_nacional = [
        (f"La TD nacional en el {c.act} fue de ", 0), (pct(N["td"], "td"), 1),
        (". Jalisco se ubica ", 0),
        (f"{abs(dif_nac):.2f} pp {'por debajo' if dif_nac < 0 else 'por encima'}"
         if dif_nac else "en el mismo nivel", 1),
        (" del promedio nacional." if dif_nac else " que el promedio nacional.", 0),
    ]
    c.t_nacional = (
        ["Período", "Jalisco", "Nacional", "Diferencia (pp)"],
        [
            [c.ant, pct(Ja["td"], "td"), pct(Na["td"], "td"), signo(dif(Ja["td"], Na["td"], "td"))],
            [c.act, pct(J["td"], "td"), pct(N["td"], "td"), signo(dif_nac)],
            ["Var. pp", signo(var), signo(dif(N["td"], Na["td"], "td")), "—"],
        ],
    )

    # ── Posicionamiento nacional ──────────────────────────────────────────
    ents = sorted(act["entidades"], key=lambda e: e["td"])
    n = len(ents)
    rank = next(i for i, e in enumerate(ents, 1) if e["cve"] == JALISCO)
    if rank <= 8:
        zona = "entre las entidades con menor desocupación del país"
    elif rank > n - 8:
        zona = "entre las entidades con mayor desocupación del país"
    else:
        zona = "en la parte media de la tabla nacional"
    c.rank, c.n = rank, n
    c.p_ranking = [
        ("Con ", 0), (pct(J["td"], "td"), 1), (", Jalisco ocupa el ", 0),
        (f"lugar {rank} de {n}", 1),
        (f" entidades federativas ordenadas de menor a mayor tasa de desocupación; "
         f"{rank - 1} entidades registraron tasas inferiores. Se ubica {zona}.", 0),
    ]
    filas = lambda lista, inicio: [[str(i), e["nombre"], pct(e["td"], "td")]
                                    for i, e in enumerate(lista, inicio)]
    c.t_menor = filas(ents[:5], 1)
    if rank > 5:
        c.t_menor += [["…", "…", "…"], [str(rank), "Jalisco ←", pct(J["td"], "td")]]
    c.t_mayor = [[str(i), e["nombre"], pct(e["td"], "td")]
                 for i, e in enumerate(ents[::-1][:5], 1)]

    # ── Comparativo regional ──────────────────────────────────────────────
    reg = [e for e in ents if e["cve"] in REGION]
    media = round(sum(r(e["td"], "td") for e in reg) / len(reg), 2)
    rank_reg = next(i for i, e in enumerate(reg, 1) if e["cve"] == JALISCO)
    d_media = round(r(J["td"], "td") - media, 2)
    if abs(d_media) < 0.05:
        frase_media = ", prácticamente igual a la tasa jalisciense."
    else:
        frase_media = (f"; Jalisco se ubica {abs(d_media):.2f} pp "
                       f"{'por debajo' if d_media < 0 else 'por encima'} de ella.")
    c.p_region = [
        ("Jalisco ocupa el ", 0), (f"{rank_reg}° lugar", 1),
        (f" con menor TD entre las {len(reg)} entidades de la región Occidente / Centro-Bajío. "
         "La media regional es ", 0), (f"{media:.2f}%", 1), (frase_media, 0),
    ]
    c.t_region = [
        [str(i), e["nombre"] + (" ←" if e["cve"] == JALISCO else ""), pct(e["td"], "td"),
         signo(round(r(e["td"], "td") - media, 2))]
        for i, e in enumerate(reg, 1)
    ] + [["", "Media regional", f"{media:.2f}%", "—"]]

    # ── Indicadores complementarios ───────────────────────────────────────
    c.t_indicadores = [
        [NOMBRES[k], pct(Ja[k], k), pct(J[k], k),
         signo(dif(J[k], Ja[k], k), DECIMALES[k]), pct(N[k], k)]
        for k in NOMBRES
    ]
    v = {k: dif(J[k], Ja[k], k) for k in NOMBRES}
    rank_sub = next(i for i, e in enumerate(sorted(act["entidades"], key=lambda e: e["subocupacion"]), 1)
                    if e["cve"] == JALISCO)
    d_til = dif(J["til1"], N["til1"], "til1")
    sube = lambda x, si, no: si if x > 0 else no
    c.notas = [
        f"La TD {sube(v['td'], 'aumentó', 'disminuyó')} {abs(v['td']):.2f} pp: "
        f"{sube(v['td'], 'más', 'menos')} personas buscan activamente empleo sin encontrarlo, "
        f"en proporción a la PEA. {sube(v['td'], 'Desfavorable.', 'Favorable.')}",
        f"La TPEA {sube(v['tpea'], 'aumentó', 'disminuyó')} {abs(v['tpea']):.1f} pp: una proporción "
        f"{sube(v['tpea'], 'mayor', 'menor')} de la población en edad de trabajar participó "
        f"activamente en el mercado laboral en {c.act} frente a {c.ant}.",
        f"La TIL1 {sube(v['til1'], 'aumentó', 'disminuyó')} {abs(v['til1']):.1f} pp: una proporción "
        f"{sube(v['til1'], 'mayor', 'menor')} de los ocupados trabaja en la informalidad. "
        f"Se mantiene {abs(d_til):.1f} pp {'por debajo' if d_til < 0 else 'por encima'} del "
        f"promedio nacional ({pct(N['til1'], 'til1')})"
        + ("; la tendencia merece seguimiento." if v["til1"] > 0 else "."),
        f"La subocupación {sube(v['subocupacion'], 'subió', 'bajó')} {abs(v['subocupacion']):.1f} pp "
        f"({pct(J['subocupacion'], 'subocupacion')}). "
        + ("Es la tasa de subocupación más baja del país"
           if rank_sub == 1 else f"Jalisco tiene la {rank_sub}ª tasa de subocupación más baja del país")
        + f" (nacional: {pct(N['subocupacion'], 'subocupacion')}).",
    ]

    # ── Indicadores por sexo ──────────────────────────────────────────────
    (H, Ha), (M, Ma) = c.sexo["hombres"], c.sexo["mujeres"]
    brecha_td = dif(M["td"], H["td"], "td")
    brecha_tpea = dif(M["tpea"], H["tpea"], "tpea")
    c.p_sexo = [
        (f"En el {c.act} la TD de las mujeres fue de ", 0), (pct(M["td"], "td"), 1),
        (" y la de los hombres de ", 0), (pct(H["td"], "td"), 1),
        (", una brecha de ", 0), (f"{signo(brecha_td)} pp", 1),
        (" (mujeres menos hombres). La participación económica de las mujeres (", 0),
        (pct(M["tpea"], "tpea"), 1),
        (f") se ubica {abs(brecha_tpea):.1f} pp "
         f"{'por debajo' if brecha_tpea < 0 else 'por encima'} de la de los hombres (", 0),
        (pct(H["tpea"], "tpea"), 1), (").", 0),
    ]
    c.t_sexo = [
        [CORTOS[k], pct(J[k], k), pct(H[k], k), pct(M[k], k),
         f"{signo(dif(M[k], H[k], k), DECIMALES[k])} pp"]
        for k in NOMBRES
    ]
    c.t_sexo_var = [
        [CORTOS[k], signo(dif(H[k], Ha[k], k), DECIMALES[k]), signo(dif(M[k], Ma[k], k), DECIMALES[k])]
        for k in NOMBRES
    ]

    c.fuentes = [
        f"Fuente: INEGI | Encuesta Nacional de Ocupación y Empleo (ENOE), microdatos {c.ant} y {c.act}",
        "Cálculos propios con la metodología de INEGI: población de 15 años y más, "
        "factor de expansión trimestral",
        "Jalisco (CVE 14) · Series originales (sin ajuste estacional), periodicidad trimestral",
        f"Proyecto de Aplicación Profesional — Economía, ITESO · {anio}",
    ]
    return c


# ── Salida .txt ───────────────────────────────────────────────────────────────

def _parrafo_txt(partes, ancho=95):
    # Los espacios dentro de negritas se protegen para no partir un *...* en dos líneas
    texto = "".join(f"*{t.replace(' ', chr(0))}*" if b else t for t, b in partes)
    return textwrap.fill(texto, ancho, break_on_hyphens=False).replace(chr(0), " ")


def _tabla_txt(encabezados, filas):
    anchos = [max(len(str(x)) for x in col) for col in zip(encabezados, *filas)]
    linea = lambda celdas: "  ".join(str(x).ljust(a) for x, a in zip(celdas, anchos)).rstrip()
    return "\n".join([linea(encabezados), linea(["─" * a for a in anchos])]
                     + [linea(f) for f in filas])


def generar_txt(c: SimpleNamespace, ruta):
    s = []
    seccion = lambda titulo, sub="": s.extend(
        ["", REGLA, f"*{titulo}*"] + ([sub] if sub else []) + [REGLA, ""])

    s += [f"*{c.titulo}*", "",
          "_*Cifras en porcentaje (%) de la Población Económicamente Activa (PEA)._",
          "_*Series originales (sin ajuste estacional), periodicidad trimestral._"]

    seccion("Análisis Anual", "Último trimestre disponible vs mismo trimestre del año anterior.")
    s += [_parrafo_txt(c.p_anual), "", _parrafo_txt(c.p_nacional), "",
          f"*Comparativo Jalisco vs Nacional — {c.act}:*", _tabla_txt(*c.t_nacional)]

    seccion("Posicionamiento Nacional", f"TD de Jalisco vs entidades federativas — {c.act}")
    s += [_parrafo_txt(c.p_ranking), "",
          f"*Top 5 entidades con menor TD ({c.act}):*",
          _tabla_txt(["Lugar", "Estado", "TD (%)"], c.t_menor), "",
          f"*Top 5 entidades con mayor TD ({c.act}):*",
          _tabla_txt(["Lugar", "Estado", "TD (%)"], c.t_mayor)]

    seccion(f"Comparativo Regional — Occidente / Centro-Bajío ({c.act})")
    s += [_parrafo_txt(c.p_region), "",
          _tabla_txt(["Lugar", "Estado", "TD (%)", "vs Media regional (pp)"], c.t_region)]

    seccion("Indicadores Complementarios del Mercado Laboral",
            f"Comparativo anual: {c.act} vs {c.ant} — Jalisco")
    s += [_tabla_txt(["Indicador", c.ant, c.act, "Var. (pp)", f"Nacional {c.act}"], c.t_indicadores),
          "", "Notas de interpretación:"]
    s += [textwrap.fill(n, 95, initial_indent="· ", subsequent_indent="  ", break_on_hyphens=False) for n in c.notas]

    seccion(f"Indicadores por Sexo — Jalisco {c.act}")
    s += [_parrafo_txt(c.p_sexo), "",
          _tabla_txt(["Indicador", "Total", "Hombres", "Mujeres", "Brecha M−H"], c.t_sexo), "",
          f"*Variación anual por sexo ({c.ant} → {c.act}, pp):*",
          _tabla_txt(["Indicador", "Hombres", "Mujeres"], c.t_sexo_var), "",
          "_Las estimaciones por sexo a nivel estatal tienen mayor error de muestreo que el total; "
          "las variaciones pequeñas deben interpretarse con cautela._"]

    s += ["", ""] + [f"_{linea}_" for linea in c.fuentes]
    Path(ruta).write_text("\n".join(s) + "\n", encoding="utf-8")


# ── Salida .docx ──────────────────────────────────────────────────────────────

FUENTE = "Calibri"
T_NORMAL, T_CHICA, T_TITULO = Pt(10), Pt(9), Pt(13)


def _run(p, texto, size=T_NORMAL, bold=False, italic=False):
    run = p.add_run(texto)
    run.font.name, run.font.size, run.font.bold, run.font.italic = FUENTE, size, bold, italic


def _p(doc, partes=(), size=T_NORMAL, italic=False, antes=3, despues=3, sangria=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(antes), Pt(despues)
    if sangria:
        p.paragraph_format.left_indent = Cm(sangria)
    if isinstance(partes, str):
        partes = [(partes, 0)]
    for texto, bold in partes:
        _run(p, texto, size, bool(bold), italic)
    return p


def _regla(doc):
    p = _p(doc, antes=4, despues=4)
    p.paragraph_format.keep_with_next = True
    borde = OxmlElement("w:pBdr")
    abajo = OxmlElement("w:bottom")
    for k, v in {"val": "single", "sz": "6", "space": "1", "color": "888888"}.items():
        abajo.set(qn(f"w:{k}"), v)
    borde.append(abajo)
    p._p.get_or_add_pPr().append(borde)


def _seccion(doc, titulo, sub=""):
    _regla(doc)
    p = _p(doc, [(titulo, 1)], antes=8, despues=2)
    p.paragraph_format.keep_with_next = True
    if sub:
        _run(p, f"  —  {sub}", T_CHICA)


def _tabla(doc, encabezados, filas, anchos_cm, primera_izq=False):
    # El párrafo anterior (título de la tabla) se mantiene junto a la tabla
    doc.paragraphs[-1].paragraph_format.keep_with_next = True
    t = doc.add_table(rows=1 + len(filas), cols=len(encabezados))
    t.style, t.alignment, t.autofit = "Table Grid", WD_TABLE_ALIGNMENT.LEFT, False
    for j, ancho in enumerate(anchos_cm):
        t.columns[j].width = Cm(ancho)
    ultima = len(filas)
    for i, fila in enumerate([encabezados] + filas):
        for j, valor in enumerate(fila):
            celda = t.cell(i, j)
            celda.width = Cm(anchos_cm[j])
            p = celda.paragraphs[0]
            izq = primera_izq and j == (1 if encabezados[0] == "Lugar" else 0)
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if izq else WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.keep_with_next = i < ultima   # la tabla no se parte entre páginas
            _run(p, str(valor), T_CHICA, bold=(i == 0))
    _p(doc, antes=0, despues=4)


def generar_docx(c: SimpleNamespace, ruta):
    doc = Document()
    for sec in doc.sections:
        sec.top_margin = sec.bottom_margin = Cm(2.5)
        sec.left_margin = sec.right_margin = Cm(3.0)

    _p(doc, [(c.titulo, 1)], size=T_TITULO, antes=0, despues=4)
    _p(doc, "Cifras en porcentaje (%) de la Población Económicamente Activa (PEA).",
       T_CHICA, italic=True, antes=0, despues=1)
    _p(doc, "Series originales (sin ajuste estacional), periodicidad trimestral.",
       T_CHICA, italic=True, antes=0, despues=4)

    _seccion(doc, "Análisis Anual", "Último trimestre disponible vs mismo trimestre del año anterior")
    _p(doc, c.p_anual)
    _p(doc, c.p_nacional, despues=6)
    _p(doc, [(f"Comparativo Jalisco vs Nacional — {c.act}:", 1)])
    _tabla(doc, *c.t_nacional, [3.2, 3.5, 3.5, 4.5])

    _seccion(doc, "Posicionamiento Nacional", f"TD de Jalisco vs entidades federativas — {c.act}")
    _p(doc, c.p_ranking, despues=5)
    _p(doc, [(f"Top 5 entidades con menor TD ({c.act}):", 1)])
    _tabla(doc, ["Lugar", "Estado", "TD (%)"], c.t_menor, [2.0, 8.5, 4.2], primera_izq=True)
    _p(doc, [(f"Top 5 entidades con mayor TD ({c.act}):", 1)])
    _tabla(doc, ["Lugar", "Estado", "TD (%)"], c.t_mayor, [2.0, 8.5, 4.2], primera_izq=True)

    _seccion(doc, f"Comparativo Regional — Occidente / Centro-Bajío ({c.act})")
    _p(doc, c.p_region, despues=5)
    _tabla(doc, ["Lugar", "Estado", "TD (%)", "vs Media (pp)"], c.t_region,
           [2.0, 5.5, 3.0, 4.2], primera_izq=True)

    _seccion(doc, "Indicadores Complementarios del Mercado Laboral",
             f"Comparativo anual: {c.act} vs {c.ant} — Jalisco")
    _tabla(doc, ["Indicador", c.ant, c.act, "Var. (pp)", f"Nacional {c.act}"],
           c.t_indicadores, [5.5, 2.2, 2.2, 2.2, 2.6], primera_izq=True)
    _p(doc, [("Notas de interpretación:", 1)], despues=2)
    for nota in c.notas:
        _p(doc, f"· {nota}", T_CHICA, antes=1, despues=1, sangria=1)

    _seccion(doc, f"Indicadores por Sexo — Jalisco {c.act}")
    _p(doc, c.p_sexo, despues=5)
    _tabla(doc, ["Indicador", "Total", "Hombres", "Mujeres", "Brecha M−H"], c.t_sexo,
           [3.5, 2.6, 2.6, 2.6, 3.2], primera_izq=True)
    _p(doc, [(f"Variación anual por sexo ({c.ant} → {c.act}, pp):", 1)])
    _tabla(doc, ["Indicador", "Hombres", "Mujeres"], c.t_sexo_var, [3.5, 3.0, 3.0], primera_izq=True)
    _p(doc, "Las estimaciones por sexo a nivel estatal tienen mayor error de muestreo que el total; "
            "las variaciones pequeñas deben interpretarse con cautela.", T_CHICA, italic=True)

    _regla(doc)
    for linea in c.fuentes:
        _p(doc, linea, T_CHICA, italic=True, antes=1, despues=1)
    doc.save(ruta)


# ── Uso directo ───────────────────────────────────────────────────────────────

def generar(periodo: str, carpeta_datos="datos", carpeta_salida="fichas") -> tuple[Path, Path]:
    anio, trim = map(int, re.fullmatch(r"(\d{4})_T(\d)", periodo).groups())
    c = preparar(calcular(periodo, carpeta_datos), calcular(f"{anio - 1}_T{trim}", carpeta_datos))
    salida = Path(carpeta_salida)
    salida.mkdir(parents=True, exist_ok=True)
    txt, docx = salida / f"ficha_{periodo}.txt", salida / f"ficha_{periodo}.docx"
    generar_txt(c, txt)
    generar_docx(c, docx)
    return txt, docx


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Genera la ficha ENOE Jalisco (.txt y .docx)")
    ap.add_argument("--periodo", required=True, help="AAAA_T# (ej. 2026_T2)")
    args = ap.parse_args()
    for ruta in generar(args.periodo):
        print(f"  ✅ {ruta}")
