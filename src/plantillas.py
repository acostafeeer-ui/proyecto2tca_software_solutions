"""Resumen por plantillas: determinista, sin LLM. Sirve de respaldo y para reescribir frases que no pasan el verificador."""
import re
from collections import Counter

from .config import CIE10_CRONICOS, SIGNOS, TERMINOS_CRONICOS
from .utils import normalizar

_RE_CRONICO = re.compile(r"\b(" + "|".join(re.escape(t) for t in TERMINOS_CRONICOS) + r")\b")


def es_cronico(h) -> bool:
    """Diagnóstico crónico: código CIE-10 con prefijo de CIE10_CRONICOS o descripción con un término crónico."""
    cod = re.sub(r"[^A-Z0-9]", "", str(h["detalle"].get("cie10") or "").upper())
    if cod and any(cod.startswith(p) for p in CIE10_CRONICOS):
        return True
    return bool(_RE_CRONICO.search(normalizar(h["valor"])))


def _fecha(h):
    f = h.get("fecha") or ""
    if not f:
        return ""
    u = h["detalle"].get("ultima_fecha")
    return f" (desde {f}, último registro {u})" if u else f" ({f})"


def frase_de(h) -> str:
    """Una frase fiel a un hecho, sin agregar nada."""
    d, t, v = h["detalle"], h["tipo"], h["valor"]
    if t == "diagnostico":
        cie = f", CIE-10 {d['cie10']}" if d.get("cie10") and d["cie10"] != v else ""
        return f"{v}{cie}{_fecha(h)}."
    if t == "medicamento":
        partes = [x for x in (d.get("dosis"), d.get("via"), d.get("frecuencia"), d.get("duracion")) if x]
        est = f", estatus {d['estatus']}" if d.get("estatus") else ""
        return f"{v}{': ' + ', '.join(partes) if partes else ''}{est}{_fecha(h)}."
    if t == "alergia":
        pre = "Niega alergias" if h["certeza"] == "negado" and "alerg" not in normalizar(v) else ""
        return f"{pre or v}{_fecha(h)}."
    if t == "atencion":
        extra = []
        if d.get("triage"):
            extra.append(f"triage {d['triage']}")
        if d.get("destino"):
            extra.append(f"destino {d['destino']}")
        if d.get("dias_estancia"):
            extra.append(f"{d['dias_estancia']} días de estancia")
        return f"{v}{' (' + ', '.join(extra) + ')' if extra else ''}{_fecha(h)}."
    return f"{v}{_fecha(h)}."


def _ultimos(hs, n):
    return sorted(hs, key=lambda h: h.get("detalle", {}).get("ultima_fecha") or h.get("fecha") or "", reverse=True)[:n]


def secciones_plantilla(hechos):
    T = lambda tipo, **kw: [h for h in hechos if h["tipo"] == tipo and all(h.get(k) == v for k, v in kw.items())]
    sec = {}
    dx = _ultimos(T("diagnostico", certeza="afirmado"), 10000)  # del más reciente al más antiguo
    sec["Problemas crónicos"] = [(frase_de(h), [h["id"]]) for h in dx if es_cronico(h)][:8]
    sec["Diagnósticos previos"] = [(frase_de(h), [h["id"]]) for h in dx if not es_cronico(h)][:8]
    meds = []
    vistos = set()
    for h in _ultimos(T("medicamento"), 40):
        k = normalizar(h["valor"])
        if k not in vistos:
            vistos.add(k)
            meds.append(h)
    sec["Medicamentos recientes"] = [(frase_de(h), [h["id"]]) for h in meds[:8]]
    sec["Antecedentes personales y quirúrgicos"] = [(frase_de(h), [h["id"]]) for h in
                                                    _ultimos(T("antecedente_personal", certeza="afirmado") + T("procedimiento"), 8)]
    sec["Antecedentes familiares"] = [(frase_de(h), [h["id"]]) for h in _ultimos(T("antecedente_familiar", certeza="afirmado"), 6)]
    sec["Gineco-obstétricos"] = [(frase_de(h), [h["id"]]) for h in _ultimos(T("gineco"), 5)]
    riesgo = [(frase_de(h), [h["id"]]) for h in _ultimos(T("habito"), 4)]
    imc = calcular_imc(hechos)
    if imc:
        riesgo.append(imc)
    sec["Hábitos y factores de riesgo"] = riesgo
    sec["Últimas atenciones"] = [(frase_de(h), [h["id"]]) for h in _ultimos(T("atencion"), 5)]
    estudios = [(frase_de(h), [h["id"]]) for h in _ultimos(T("estudio"), 3)]
    sec["Estudios y signos vitales recientes"] = estudios + signos_recientes(hechos)
    return sec


def calcular_imc(hechos):
    peso = _ultimos([h for h in hechos if h["tipo"] == "signo_vital" and h["detalle"].get("signo") == "Peso"], 1)
    talla = _ultimos([h for h in hechos if h["tipo"] == "signo_vital" and h["detalle"].get("signo") == "Talla"], 1)
    if not peso or not talla:
        return None
    p, t = peso[0]["detalle"]["num"], talla[0]["detalle"]["num"] / 100
    if not (20 <= p <= 350 and 1.0 <= t <= 2.3):
        return None
    imc = p / (t * t)
    cat = "obesidad" if imc >= 30 else "sobrepeso" if imc >= 25 else "bajo peso" if imc < 18.5 else "normal"
    return (f"IMC calculado {imc:.1f} ({cat}) con peso {p:g} kg y talla {t * 100:g} cm.", [peso[0]["id"], talla[0]["id"]], "calculada")


def signos_recientes(hechos):
    out = []
    sv = [h for h in hechos if h["tipo"] == "signo_vital"]
    for signo in list(SIGNOS) + ["PA"]:
        ult = _ultimos([h for h in sv if h["detalle"].get("signo") == signo], 1)
        if not ult or signo in ("Peso", "Talla"):
            continue
        h = ult[0]
        marca = ""
        if signo in SIGNOS:
            _n, _u, mn, mx, lo, hi = SIGNOS[signo]
            if lo is not None and not (lo <= h["detalle"]["num"] <= hi) and mn <= h["detalle"]["num"] <= mx:
                marca = " (fuera de rango)"
        out.append((f"{h['valor']}{marca}{_fecha(h)}.", [h["id"]]))
    return out[:7]


def encabezado(hechos):
    sexos = Counter(h["valor"].upper()[:1] for h in hechos if h["tipo"] == "demografico" and h["detalle"].get("campo") == "sexo")
    sexo_h = [h for h in hechos if h["tipo"] == "demografico" and h["detalle"].get("campo") == "sexo"]
    edad_h = _ultimos([h for h in hechos if h["tipo"] == "demografico" and h["detalle"].get("campo") == "edad"], 1)
    sangre = _ultimos([h for h in hechos if h["tipo"] == "tipo_sangre"], 1)
    ult = _ultimos([h for h in hechos if h["tipo"] == "atencion"], 1)
    return {
        "sexo": sexos.most_common(1)[0][0] if sexos else "",
        "edad": edad_h[0]["valor"] if edad_h else "",
        "tipo_sangre": sangre[0]["valor"] if sangre else "",
        "ultima_atencion": frase_de(ult[0]) if ult else "",
        "refs": [x["id"] for x in (sexo_h[:1] + edad_h + sangre + ult)],
    }


def estado_alergias(hechos):
    al = [h for h in hechos if h["tipo"] == "alergia" and h["sujeto"] == "paciente"]
    af = [h for h in al if h["certeza"] == "afirmado"]
    ng = [h for h in al if h["certeza"] == "negado"]
    if af and ng:
        estado = "contradictorio"
    elif af:
        estado = "documentada"
    elif ng:
        estado = "niega"
    else:
        estado = "no documentado"
    return {"estado": estado, "afirmadas": [frase_de(h) for h in af[:5]], "hechos": [h["id"] for h in (af[:5] + ng[:3])]}
