"""Motor de reglas: faltantes (F), contradicciones (C) y duplicidad terapéutica (D).

Cada alerta: regla, severidad (alta/media/info), mensaje, hechos (IDs), pregunta sugerida.
"""
from collections import defaultdict
from datetime import datetime

from .config import CLASES_FARMACOS, SIGNOS
from .utils import normalizar

ORDEN = {"alta": 0, "media": 1, "info": 2}


def _alerta(regla, sev, mensaje, hechos, pregunta=""):
    return {"regla": regla, "severidad": sev, "mensaje": mensaje, "hechos": [h["id"] for h in hechos][:12],
            "pregunta": pregunta}


def _sexo(v):
    n = normalizar(v)
    if n in {"f", "fem", "femenino", "mujer", "2"}:
        return "F"
    if n in {"m", "masc", "masculino", "hombre", "1"}:
        return "M"
    return n.upper()


def clase_de(texto):
    n = normalizar(texto)
    return {c for c, palabras in CLASES_FARMACOS.items() if any(p in n for p in palabras)}


def evaluar(hechos):
    A = []
    por_tipo = defaultdict(list)
    for h in hechos:
        por_tipo[h["tipo"]].append(h)

    alergias = [h for h in por_tipo["alergia"] if h["sujeto"] == "paciente"]
    afirmadas = [h for h in alergias if h["certeza"] == "afirmado"]
    negadas = [h for h in alergias if h["certeza"] == "negado"]
    meds = por_tipo["medicamento"]

    # F01 sin registro de alergias
    if not alergias:
        A.append(_alerta("F01", "alta", "Alergias no documentadas en el expediente.", [],
                         "Preguntar al paciente por alergias a medicamentos y alimentos."))

    # F02 tipo de sangre ausente
    if not por_tipo["tipo_sangre"]:
        A.append(_alerta("F02", "media", "Tipo de sangre y RH no registrados.", []))

    # F03 medicamento sin dosis, vía o frecuencia
    incompletos = [m for m in meds if m["detalle"].get("estatus", "").lower()[:4] not in ("susp", "canc")
                   and (not m["detalle"].get("dosis") or not m["detalle"].get("via") or not m["detalle"].get("frecuencia"))]
    if incompletos:
        nombres = ", ".join(sorted({m["valor"] for m in incompletos})[:4])
        A.append(_alerta("F03", "media", f"{len(incompletos)} indicación(es) de medicamento sin dosis, vía o frecuencia ({nombres}).",
                         incompletos, "Confirmar dosis, vía y frecuencia vigentes."))

    # F04 diagnóstico incompleto
    dx_inc = [d for d in por_tipo["diagnostico"] if d["detalle"].get("sin_descripcion") or d["detalle"].get("sin_codigo")]
    if dx_inc:
        A.append(_alerta("F04", "info", f"{len(dx_inc)} diagnóstico(s) con código sin descripción o descripción sin código.", dx_inc))

    # F05 ingreso sin nota de egreso
    ingresos = {h["clave_ingreso"] for h in hechos if h["tabla"] in ("NotaIngreso_HC", "NotasEvolucion") and h["clave_ingreso"]}
    egresos = {h["clave_ingreso"] for h in hechos if h["tabla"] == "notaegreso" and h["clave_ingreso"]}
    sin_egreso = sorted(ingresos - egresos)
    if sin_egreso:
        ultima = max((h["fecha"] for h in hechos if h["fecha"]), default="")
        evid = [h for h in por_tipo["atencion"] if h["clave_ingreso"] in sin_egreso]
        fin_ing = max((h["fecha"] for h in hechos if h["clave_ingreso"] in sin_egreso and h["fecha"]), default="")
        if fin_ing and ultima > fin_ing:
            A.append(_alerta("F05", "media", f"Hospitalización sin nota de egreso (ingreso {', '.join(sin_egreso[:3])}).", evid))

    # C01 sexo distinto
    sexos = defaultdict(list)
    for h in por_tipo["demografico"]:
        if h["detalle"].get("campo") == "sexo":
            sexos[_sexo(h["valor"])].append(h)
    if len(sexos) > 1:
        A.append(_alerta("C01", "alta", "Sexo registrado distinto entre registros: " + " vs ".join(sexos) + ".",
                         [v[0] for v in sexos.values()], "Confirmar el sexo del paciente y corregir el registro."))

    # C02 edad incongruente con las fechas
    nac = []
    for h in por_tipo["demografico"]:
        if h["detalle"].get("campo") == "edad" and h["fecha"]:
            try:
                edad = float(normalizar(h["valor"]).split()[0])
                nac.append((int(h["fecha"][:4]) - edad, h))
            except (ValueError, IndexError):
                pass
    if len(nac) > 1:
        lo, hi = min(nac, key=lambda x: x[0]), max(nac, key=lambda x: x[0])
        if hi[0] - lo[0] > 2:
            A.append(_alerta("C02", "media", f"Edad incongruente entre registros (año de nacimiento implícito {int(lo[0])} vs {int(hi[0])}).",
                             [lo[1], hi[1]], "Verificar la fecha de nacimiento."))

    # C03 tipo de sangre distinto
    sangres = defaultdict(list)
    for h in por_tipo["tipo_sangre"]:
        sangres[normalizar(h["valor"]).replace(" ", "")].append(h)
    if len(sangres) > 1:
        A.append(_alerta("C03", "alta", "Tipo de sangre distinto entre registros: " + " vs ".join(h[0]["valor"] for h in sangres.values()) + ".",
                         [v[0] for v in sangres.values()], "Confirmar tipo de sangre antes de cualquier transfusión."))

    # C04 alergia afirmada y negada
    if afirmadas and negadas:
        A.append(_alerta("C04", "alta", "Información contradictoria sobre alergias: hay alergia registrada y también «niega alergias».",
                         afirmadas[:2] + negadas[:2], "Confirmar con el paciente sus alergias."))

    # C05 medicamento de una clase con alergia
    clases_alergia = defaultdict(list)
    for h in afirmadas:
        for c in clase_de(h["valor"] + " " + h["texto_fuente"]):
            clases_alergia[c].append(h)
    for m in meds:
        comunes = clase_de(m["valor"]) & set(clases_alergia)
        for c in comunes:
            al = clases_alergia[c][0]
            if not m["fecha"] or not al["fecha"] or m["fecha"] >= al["fecha"]:
                A.append(_alerta("C05", "alta", f"{m['valor']} ({c}) indicado con alergia documentada a {c}.", [al, m],
                                 f"Revisar la indicación de {m['valor']}."))

    # C06 fechas imposibles
    for h in por_tipo["atencion"]:
        fi, fe = h["detalle"].get("fecha_ingreso"), h["detalle"].get("fecha_egreso")
        if fi and fe and fe < fi:
            A.append(_alerta("C06", "alta", f"Fecha de egreso ({fe}) anterior a la de ingreso ({fi}).", [h]))
    hoy = datetime.now().strftime("%Y-%m-%d")
    futuras = [h for h in hechos if h["fecha"] and h["fecha"] > hoy]
    if futuras:
        A.append(_alerta("C06", "media", f"{len(futuras)} registro(s) con fecha futura.", futuras))
    if por_tipo["defuncion"]:
        fd = min(h["fecha"] for h in por_tipo["defuncion"] if h["fecha"]) if any(h["fecha"] for h in por_tipo["defuncion"]) else ""
        posteriores = [h for h in hechos if fd and h["fecha"] and h["fecha"] > fd and h["tipo"] != "defuncion"]
        if posteriores:
            A.append(_alerta("C06", "alta", f"{len(posteriores)} registro(s) posteriores a la defunción registrada ({fd}).",
                             por_tipo["defuncion"][:1] + posteriores))

    # C07 signos vitales imposibles
    imposibles = []
    for h in por_tipo["signo_vital"]:
        d = h["detalle"]
        if d.get("signo") == "PA":
            if d["sis"] <= d["dia"] or d["sis"] > 300 or d["dia"] < 10:
                imposibles.append(h)
        elif d.get("signo") in SIGNOS:
            _n, _u, mn, mx, *_ = SIGNOS[d["signo"]]
            if not (mn <= d["num"] <= mx):
                imposibles.append(h)
    if imposibles:
        A.append(_alerta("C07", "media", f"{len(imposibles)} signo(s) vital(es) fuera de rango fisiológico: "
                         + "; ".join(h["valor"] for h in imposibles[:3]) + ".", imposibles, "Verificar error de captura."))

    # D01 duplicidad terapéutica: mismo principio activo, mismo día, registros distintos
    por_dia = defaultdict(list)
    for m in meds:
        if m["fecha"] and m["detalle"].get("estatus", "").lower()[:4] not in ("susp", "canc"):
            principio = normalizar(m["valor"]).split(" ")[0]
            por_dia[(principio, m["fecha"])].append(m)
    for (principio, dia), grupo in por_dia.items():
        variantes = {(normalizar(g["detalle"].get("dosis", "")), normalizar(g["detalle"].get("via", ""))) for g in grupo}
        if len(grupo) > 1 and len(variantes) > 1:
            A.append(_alerta("D01", "alta", f"Posible duplicidad terapéutica: {principio} indicado {len(grupo)} veces el {dia} con distinta dosis o vía.",
                             grupo, f"Confirmar cuál indicación de {principio} está vigente."))

    A.sort(key=lambda a: ORDEN[a["severidad"]])
    return A
