"""Interfaz para el médico: agenda -> cita -> resumen verificado con evidencia.

Uso:
    streamlit run app.py
"""
from datetime import date

import pandas as pd
import streamlit as st

from src.config import DB_PATH
from src.llm import disponible

st.set_page_config(page_title="Insight Clínico Verificable", layout="wide")

st.markdown("""
<style>
.chip {display:inline-block; padding:1px 7px; margin:0 2px; border:1px solid #9aa0a6; border-radius:10px;
       font-size:0.75rem; font-family:monospace; color:#3c4043;}
.frase {margin:2px 0 6px 0; line-height:1.45;}
.reescrita {border-left:3px solid #b26a00; padding-left:6px;}
.sev-alta {border-left:4px solid #b3261e; padding:6px 10px; margin-bottom:6px; background:rgba(179,38,30,0.06);}
.sev-media {border-left:4px solid #b26a00; padding:6px 10px; margin-bottom:6px; background:rgba(178,106,0,0.06);}
.sev-info {border-left:4px solid #6b6b6b; padding:6px 10px; margin-bottom:6px; background:rgba(0,0,0,0.03);}
.small {font-size:0.82rem; color:#5f6368;}
</style>""", unsafe_allow_html=True)

if not DB_PATH.exists():
    st.title("Insight Clínico Verificable")
    st.error("No existe la base de datos. Ejecuta primero:  python ingest.py --parquet datos/")
    st.stop()

from src.datos import agenda  # noqa: E402
from src.pipeline import generar_resumen  # noqa: E402

# ---------------- barra lateral: agenda ----------------
with st.sidebar:
    st.header("Agenda del día")
    fecha_cita = st.date_input("Fecha de la cita", value=date.today())
    opciones_modo = ["Gemini", "Groq", "Plantilla (sin LLM)"]
    modo_ui = st.radio("Motor de redacción", opciones_modo, index=1 if disponible("groq") else (0 if disponible("gemini") else 2))
    modo = {"Gemini": "gemini", "Groq": "groq", "Plantilla (sin LLM)": "plantilla"}[modo_ui]
    if modo != "plantilla" and not disponible(modo):
        st.warning(f"No hay llave de {modo_ui} en .env; se usará el modo plantilla.")

    @st.cache_data(show_spinner=False)
    def _agenda():
        return agenda(30)

    ag = _agenda()
    buscar = st.text_input("Buscar expediente")
    if buscar:
        ag = pd.concat([pd.DataFrame([{"expediente": buscar.strip(), "registros": None, "tablas": None}]), ag])
    horas = [f"{8 + i // 4:02d}:{(i % 4) * 15:02d}" for i in range(len(ag))]
    etiquetas = [f"{h}  ·  Exp. {e}" + (f"  ({int(r)} reg.)" if pd.notna(r) else "")
                 for h, e, r in zip(horas, ag["expediente"], ag["registros"])]
    with st.container(height=360):
        elegido = st.radio("Citas", etiquetas, label_visibility="collapsed") if etiquetas else None
    expediente = ag["expediente"].iloc[etiquetas.index(elegido)] if elegido else None
    generar = st.button("Abrir cita", type="primary", width="stretch", disabled=expediente is None)

if "cache" not in st.session_state:
    st.session_state.cache = {}

clave = (expediente, str(fecha_cita), modo)
if generar and expediente:
    with st.spinner("Leyendo expediente y verificando el resumen..."):
        st.session_state.cache[clave] = generar_resumen(expediente, str(fecha_cita), modo)
    st.session_state.actual = clave

res = st.session_state.cache.get(st.session_state.get("actual"))
if not res:
    st.title("Insight Clínico Verificable")
    st.write("Selecciona una cita en la agenda y da clic en **Abrir cita**.")
    st.caption("La IA lee y redacta, el código verifica, el médico decide.")
    st.stop()

ev = res["evidencia"]


def chips(refs):
    return " ".join(f"<span class='chip'>{r}</span>" for r in refs)


def detalle_refs(refs):
    for r in refs:
        e = ev.get(r)
        if not e:
            continue
        st.markdown(f"**{r}** · `{e['ref']}` · {e['fecha'] or 'sin fecha'} · {e['certeza']}")
        st.caption(e["texto_fuente"])
        if e["refs_extra"]:
            st.caption("También en: " + ", ".join(e["refs_extra"][:8]) + (" ..." if len(e["refs_extra"]) > 8 else ""))


# ---------------- encabezado ----------------
enc, fid = res["encabezado"], res["fidelidad"]
st.subheader(f"Expediente {res['expediente']}")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Edad", enc["edad"] or "—")
c2.metric("Sexo", enc["sexo"] or "—")
c3.metric("Tipo de sangre", enc["tipo_sangre"] or "—")
total = fid["verificadas"] + fid["reescritas"]
c4.metric("Frases verificadas", f"{fid['verificadas']}/{total}")
c5.metric("Tiempo", f"{res['estadisticas']['segundos']} s")
st.caption(f"Última atención: {enc['ultima_atencion'] or 'sin registro'} · Cita: {res['fecha_cita']} · "
           f"Motor: {res['modo']} · {res['estadisticas']['registros_fuente']} registros fuente, "
           f"{res['estadisticas']['duplicados_colapsados']} duplicados colapsados")

# ---------------- alergias ----------------
al = res["alergias"]
if al["estado"] == "contradictorio":
    st.error("ALERGIAS: información contradictoria. " + " ".join(al["afirmadas"]))
elif al["estado"] == "documentada":
    st.error("ALERGIAS: " + " ".join(al["afirmadas"]))
elif al["estado"] == "niega":
    st.success("Alergias: el paciente niega alergias.")
else:
    st.warning("ALERGIAS: no documentado en el expediente. Preguntar al paciente.")
if al["hechos"]:
    with st.expander("Fuentes de alergias"):
        detalle_refs(al["hechos"])

tab_res, tab_ev, tab_aud, tab_json = st.tabs(["Resumen", "Evidencia", "Modo auditor", "JSON"])

with tab_res:
    izq, der = st.columns([2, 3])
    with izq:
        st.markdown("#### Alertas")
        if not res["alertas"]:
            st.write("Sin alertas.")
        for a in res["alertas"]:
            st.markdown(f"<div class='sev-{a['severidad']}'><b>{a['regla']} · {a['severidad'].upper()}</b><br>{a['mensaje']}"
                        + (f"<br><span class='small'>Sugerencia: {a['pregunta']}</span>" if a["pregunta"] else "")
                        + (f"<br>{chips(a['hechos'])}" if a["hechos"] else "") + "</div>", unsafe_allow_html=True)
            if a["hechos"]:
                with st.popover("Ver fuentes", width="content"):
                    detalle_refs(a["hechos"])
    with der:
        st.markdown("#### Resumen clínico")
        for s in res["secciones"]:
            if not s["frases"]:
                continue
            st.markdown(f"**{s['titulo']}**")
            for i, f in enumerate(s["frases"]):
                cls = "frase reescrita" if f["estado"] == "reescrita" else "frase"
                a, b = st.columns([12, 2])
                a.markdown(f"<div class='{cls}'>{f['texto']} {chips(f['refs'])}</div>", unsafe_allow_html=True)
                with b.popover("Fuente"):
                    detalle_refs(f["refs"])

with tab_ev:
    df = pd.DataFrame([{"id": k, **{c: v[c] for c in ("tipo", "valor", "fecha", "certeza", "ref")},
                        "registros": 1 + len(v["refs_extra"])} for k, v in ev.items()])
    tipo = st.multiselect("Tipo de hecho", sorted(df["tipo"].unique()) if len(df) else [])
    vista = df[df["tipo"].isin(tipo)] if tipo else df
    st.dataframe(vista, width="stretch", hide_index=True, height=480)

with tab_aud:
    st.write(f"Verificadas: {fid['verificadas']} · Reescritas: {fid['reescritas']} · Eliminadas: {fid['eliminadas']}")
    if res["auditoria"]:
        st.dataframe(pd.DataFrame(res["auditoria"]), width="stretch", hide_index=True)
    else:
        st.write("Ninguna frase fue eliminada ni reescrita.")
    if res["estadisticas"].get("llm"):
        st.json(res["estadisticas"]["llm"])

with tab_json:
    st.json({k: v for k, v in res.items() if k != "evidencia"}, expanded=False)
