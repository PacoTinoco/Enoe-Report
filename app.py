"""
app.py — Dashboard ENOE Jalisco
===============================
Uso:  streamlit run app.py
"""

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import calendario
from generar_ficha import preparar
from pipeline_trimestral import borrar_ficha, leer_estado

st.set_page_config(page_title="ENOE Jalisco · Indicadores Laborales", page_icon="📊", layout="wide")

BASE   = Path(__file__).parent
DATOS  = BASE / "datos"
FICHAS = BASE / "fichas"

INDICADORES = {
    "Tasa de Desocupación (TD)": ("td", BASE / "serie_bie_jalisco.csv", "% de la PEA",
                                  "Serie histórica 2005 T1 – presente"),
    "Tasa de Participación Económica (TPEA)": ("tpea", BASE / "serie_indicadores_jalisco.csv",
                                               "% de la población de 15 años y más", "2024 T4 – presente"),
    "Tasa de Informalidad Laboral (TIL1)": ("til1", BASE / "serie_indicadores_jalisco.csv",
                                            "% de la población ocupada", "2024 T4 – presente"),
    "Tasa de Subocupación": ("subocupacion", BASE / "serie_indicadores_jalisco.csv",
                             "% de la población ocupada", "2024 T4 – presente"),
}
AZUL, NARANJA, ROJO = "#1f77b4", "#ff7f0e", "#d62728"


# ── Helpers ───────────────────────────────────────────────────────────────────

def etiqueta(periodo: str) -> str:
    anio, trim = periodo.split("_T")
    return f"{trim}° Trim {anio}"

def a_fecha(periodo: str):
    anio, trim = map(int, periodo.split("_T"))
    return pd.Timestamp(anio, trim * 3, 1)

def anterior(periodo: str) -> str:
    anio, trim = periodo.split("_T")
    return f"{int(anio) - 1}_T{trim}"

def hora_cdmx(iso: str) -> str | None:
    """'2026-10-02T19:44:00Z' → '02/10/2026 13:44' (hora del centro de México)."""
    momento = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if momento.tzinfo is None:                 # registros viejos sin zona horaria: no se sabe cuál es
        return None
    return momento.astimezone(calendario.CDMX).strftime("%d/%m/%Y %H:%M")

@st.cache_data(ttl=30)
def serie(ruta: Path, col: str) -> pd.DataFrame:
    if not ruta.exists():
        return pd.DataFrame()
    df = pd.read_csv(ruta)
    if col not in df.columns:
        return pd.DataFrame()
    df = df.dropna(subset=[col]).copy()
    df["fecha"] = df["periodo"].apply(a_fecha)
    return df.sort_values("fecha").reset_index(drop=True)

@st.cache_data(ttl=30)
def contexto_ultimo():
    """Contexto de la ficha más reciente (necesita el trimestre y el del año anterior)."""
    disponibles = sorted(p.stem.replace("indicadores_", "") for p in DATOS.glob("indicadores_*.json"))
    for periodo in reversed(disponibles):
        if anterior(periodo) in disponibles:
            leer = lambda p: json.loads((DATOS / f"indicadores_{p}.json").read_text(encoding="utf-8"))
            return periodo, preparar(leer(periodo), leer(anterior(periodo)))
    return None, None


periodo, c = contexto_ultimo()

# ── Encabezado y KPIs ─────────────────────────────────────────────────────────
st.title("📊 Indicadores Laborales · Jalisco")
st.caption("Encuesta Nacional de Ocupación y Empleo (ENOE) · INEGI  |  "
           "Proyecto de Aplicación Profesional — Economía, ITESO")
prox = calendario.proxima(calendario.guardadas())
if prox:
    st.caption(f"📅 Próxima publicación de INEGI: **{etiqueta(prox['periodo'])}** — "
               f"{prox['fecha'][8:10]}/{prox['fecha'][5:7]}/{prox['fecha'][:4]} a las 06:00")

if c:
    (H, _), (M, _) = c.sexo["hombres"], c.sexo["mujeres"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("TD Jalisco", f"{c.J['td']:.2f}%",
              delta=f"{c.J['td'] - c.Ja['td']:+.2f} pp vs año anterior", delta_color="inverse")
    k2.metric("Último período", etiqueta(periodo), help=f"Lugar {c.rank} de {c.n} entidades en TD")
    k3.metric("TD hombres", f"{H['td']:.2f}%")
    k4.metric("TD mujeres", f"{M['td']:.2f}%")
else:
    st.info("Todavía no hay indicadores calculados. Genera la primera ficha en la pestaña ⚙️.")

# ── Robot en GitHub ─────────────────────────────────────────────────────────────
# En la nube (Streamlit Community Cloud) el botón dispara el robot de GitHub Actions:
# la ficha se genera allá, se manda por correo y se guarda en el repositorio, y la app
# se actualiza sola. En una computadora local, el botón corre el pipeline directamente.

def secreto(seccion: str, clave: str):
    try:
        return st.secrets[seccion][clave]
    except Exception:
        return None

GH_TOKEN, GH_REPO = secreto("github", "token"), secreto("github", "repo")
CLAVE_APP = secreto("app", "clave")
EN_NUBE = bool(GH_TOKEN and GH_REPO)
GH_API = f"https://api.github.com/repos/{GH_REPO}/actions/workflows/robot.yml"
GH_HEADERS = {"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json",
              "X-GitHub-Api-Version": "2022-11-28"}


def ultimas_ejecuciones(n=5) -> list[dict]:
    r = requests.get(f"{GH_API}/runs", headers=GH_HEADERS, params={"per_page": n}, timeout=30)
    r.raise_for_status()
    return r.json()["workflow_runs"]


def disparar_robot(inputs: dict, mensaje_ok: str):
    """Corre el robot en GitHub Actions con estos inputs y espera a que termine."""
    inicio = datetime.now(timezone.utc) - timedelta(seconds=10)
    r = requests.post(f"{GH_API}/dispatches", headers=GH_HEADERS, timeout=30,
                      json={"ref": "main", "inputs": inputs})
    if r.status_code != 204:
        st.error(f"GitHub rechazó la solicitud ({r.status_code}): {r.text[:300]}")
        return
    estado = st.empty()
    for _ in range(60):                                    # hasta ~5 minutos
        time.sleep(5)
        run = next((x for x in ultimas_ejecuciones() if x["event"] == "workflow_dispatch"
                    and datetime.fromisoformat(x["created_at"].replace("Z", "+00:00")) >= inicio), None)
        if not run:
            estado.info("⏳ Enviando la solicitud al robot...")
            continue
        if run["status"] != "completed":
            estado.info(f"⏳ El robot está trabajando ({run['status']}). [Ver detalle]({run['html_url']})")
            continue
        if run["conclusion"] == "success":
            estado.success(mensaje_ok)
            st.cache_data.clear()
        else:
            estado.error(f"❌ El robot terminó con error. [Ver detalle]({run['html_url']})")
        return
    estado.warning("El robot sigue trabajando. Revisa el avance en GitHub → Actions.")


st.divider()
tab1, tab2, tab3, tab4 = st.tabs(["📈 Serie histórica", "👥 Por sexo", "📄 Fichas", "⚙️ Generar ficha"])


# ── Serie histórica ───────────────────────────────────────────────────────────
with tab1:
    nombre = st.selectbox("Indicador", list(INDICADORES))
    col, ruta, unidad, nota = INDICADORES[nombre]
    df = serie(ruta, col)
    if df.empty:
        st.warning(f"No hay datos para {nombre}.")
    else:
        st.caption(nota)
        anios = sorted(df["anio"].unique())
        if len(anios) > 1:
            desde, hasta = st.select_slider("Rango de años", options=anios,
                                            value=(max(anios[0], anios[-1] - 10), anios[-1]))
            df = df[df["anio"].between(desde, hasta)]
        ult = df.iloc[-1]
        fig = go.Figure([
            go.Scatter(x=df["fecha"], y=df[col], mode="lines+markers", name=nombre,
                       line=dict(color=AZUL, width=2),
                       hovertemplate="%{x|%b %Y} · <b>%{y:.2f}%</b><extra></extra>"),
            go.Scatter(x=[ult["fecha"]], y=[ult[col]], mode="markers", name=etiqueta(ult["periodo"]),
                       marker=dict(color=ROJO, size=11),
                       hovertemplate=f"<b>{etiqueta(ult['periodo'])}</b>: %{{y:.2f}}%<extra></extra>"),
        ])
        fig.update_layout(title=f"{nombre} — Jalisco", yaxis_title=unidad, height=420,
                          hovermode="x unified", legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, width="stretch")

        tabla = df.tail(8).iloc[::-1].copy()
        previo = dict(zip(serie(ruta, col)["periodo"], serie(ruta, col)[col]))
        tabla["Var. anual (pp)"] = [
            f"{v - previo[anterior(p)]:+.2f}" if anterior(p) in previo else "—"
            for p, v in zip(tabla["periodo"], tabla[col])
        ]
        tabla["Período"] = tabla["periodo"].apply(etiqueta)
        tabla["Valor"] = tabla[col].map(lambda v: f"{v:.2f}%")
        st.dataframe(tabla[["Período", "Valor", "Var. anual (pp)"]], hide_index=True,
                     width="stretch")


# ── Por sexo ──────────────────────────────────────────────────────────────────
with tab2:
    if not c:
        st.info("Genera una ficha para ver los indicadores por sexo.")
    else:
        st.caption(f"Jalisco · {c.act} vs {c.ant} · microdatos ENOE")
        claves = {"TD": "td", "TPEA": "tpea", "TIL1": "til1", "Subocupación": "subocupacion"}
        corto = st.radio("Indicador", list(claves), horizontal=True)
        k = claves[corto]
        (H, Ha), (M, Ma) = c.sexo["hombres"], c.sexo["mujeres"]
        fig = go.Figure([
            go.Bar(name="Hombres", x=[c.ant, c.act], y=[Ha[k], H[k]], marker_color=AZUL,
                   text=[f"{Ha[k]:.2f}%", f"{H[k]:.2f}%"], textposition="outside"),
            go.Bar(name="Mujeres", x=[c.ant, c.act], y=[Ma[k], M[k]], marker_color=NARANJA,
                   text=[f"{Ma[k]:.2f}%", f"{M[k]:.2f}%"], textposition="outside"),
        ])
        fig.update_layout(barmode="group", title=f"{corto} por sexo — Jalisco", yaxis_title="%",
                          height=400, legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch")

        izq, der = st.columns([3, 2])
        izq.markdown(f"**{c.act}**")
        izq.dataframe(pd.DataFrame(c.t_sexo, columns=["Indicador", "Total", "Hombres", "Mujeres", "Brecha M−H"]),
                      hide_index=True, width="stretch")
        der.markdown(f"**Variación anual (pp)**")
        der.dataframe(pd.DataFrame(c.t_sexo_var, columns=["Indicador", "Hombres", "Mujeres"]),
                      hide_index=True, width="stretch")
        st.caption("Las estimaciones por sexo a nivel estatal tienen mayor error de muestreo que el total.")


# ── Fichas ────────────────────────────────────────────────────────────────────
# Hay un solo archivo por trimestre (ficha_AAAA_T#): al regenerarla se sobrescribe, no se duplica.
with tab3:
    fichas = sorted(FICHAS.glob("ficha_*.txt"), reverse=True)
    generadas = leer_estado().get("generadas", {})
    if not fichas:
        st.info("No hay fichas generadas todavía.")
    for i, txt in enumerate(fichas):
        per = txt.stem.replace("ficha_", "")
        docx = txt.with_suffix(".docx")
        fecha = hora_cdmx(generadas[per]) if per in generadas else None
        titulo = f"📄 {etiqueta(per)}" + (f"  ·  generada el {fecha} (hora CDMX)" if fecha else "")
        with st.expander(titulo, expanded=(i == 0)):
            texto, botones = st.columns([3, 1])
            texto.text(txt.read_text(encoding="utf-8"))
            botones.download_button("📥 Descargar .docx", docx.read_bytes() if docx.exists() else b"",
                                    file_name=docx.name, disabled=not docx.exists(),
                                    key=f"docx_{per}", width="stretch",
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            botones.download_button("📥 Descargar .txt", txt.read_bytes(), file_name=txt.name,
                                    mime="text/plain", key=f"txt_{per}", width="stretch")
            with botones.popover("🗑️ Borrar ficha", width="stretch"):
                st.warning(f"Se borrarán el .txt y el .docx de {etiqueta(per)}. "
                           "Se puede volver a generar en la pestaña ⚙️.")
                clave_b = st.text_input("Clave", type="password", key=f"clave_b_{per}") if CLAVE_APP else ""
                if st.button("Confirmar borrado", key=f"borrar_{per}", type="primary"):
                    if CLAVE_APP and clave_b != CLAVE_APP:
                        st.error("Clave incorrecta.")
                    elif EN_NUBE:
                        disparar_robot({"borrar": per}, f"🗑️ Ficha {etiqueta(per)} borrada. "
                                       "La app se actualiza en 1–2 minutos (recarga la página).")
                    else:
                        borrar_ficha(per)
                        st.rerun()


def correr_local(periodo: str, sin_email: bool, forzar: bool):
    cmd = [sys.executable, str(BASE / "pipeline_trimestral.py")]
    cmd += ["--periodo", periodo] * bool(periodo) + ["--sin-email"] * sin_email + ["--forzar"] * forzar
    log, salida = st.empty(), ""
    with st.spinner("Generando ficha..."):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=BASE)
        for linea in proc.stdout:
            salida += linea
            log.code(salida)
        proc.wait()
    if proc.returncode == 0:
        st.success("✅ Listo. La ficha está en la pestaña 📄 Fichas.")
        st.cache_data.clear()
    else:
        st.error("❌ Hubo un error; revisa el registro de arriba.")


with tab4:
    st.markdown("Descarga los microdatos de la ENOE, calcula los indicadores y genera la ficha "
                "en **.txt** y **.docx**."
                + (" La ficha también se envía por correo a la lista configurada." if EN_NUBE else ""))
    with st.form("generar"):
        per_txt = st.text_input("Trimestre (vacío = el más reciente publicado)", placeholder="ej. 2026_T3")
        c1, c2 = st.columns(2)
        sin_email = c1.checkbox("No enviar correo", value=not EN_NUBE)
        forzar = c2.checkbox("Rehacer aunque ya exista", value=False)
        clave = st.text_input("Clave", type="password") if CLAVE_APP else ""
        correr = st.form_submit_button("▶  Generar ficha", type="primary")

    if correr:
        periodo = per_txt.strip()
        if periodo and not re.fullmatch(r"\d{4}_T[1-4]", periodo):
            st.error("Formato incorrecto. Usa AAAA_T# (ej. 2026_T3).")
        elif CLAVE_APP and clave != CLAVE_APP:
            st.error("Clave incorrecta.")
        elif EN_NUBE:
            disparar_robot({"periodo": periodo, "sin_email": str(sin_email).lower(),
                            "forzar": str(forzar).lower()},
                           "✅ Listo. La ficha se guardó en el repositorio y la app se actualiza en "
                           "1–2 minutos (recarga la página).")
        else:
            correr_local(periodo, sin_email, forzar)

    if EN_NUBE:
        with st.expander("🤖 Últimas ejecuciones del robot"):
            try:
                for run in ultimas_ejecuciones():
                    icono = {"success": "✅", "failure": "❌"}.get(run["conclusion"], "⏳")
                    tipo = "programada" if run["event"] == "schedule" else "manual"
                    st.markdown(f"{icono} {hora_cdmx(run['created_at'])} (hora CDMX) · {tipo} · "
                                f"[ver]({run['html_url']})")
            except Exception as e:
                st.caption(f"No se pudo consultar GitHub: {e}")
