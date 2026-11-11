"""Libro de evidencia: convierte los registros de un paciente en hechos con su referencia exacta.

Cada hecho tiene: id, expediente, tipo, valor, detalle, fecha, ref (Tabla#Indice.Campo),
texto_fuente, certeza (afirmado/negado/sospecha) y sujeto (paciente/familiar).
"""
import re

import pandas as pd

from .config import (DIAGNOSTICOS, FAMILIAR, FECHA_TABLA, NEGACION, PSEUDO_NEGACION, SIGNOS,
                     TEXTO_LIBRE)
from .datos import registros_paciente
from .utils import Fila, fecha_iso, normalizar, numero, oraciones, parse_fecha

NO = {"no", "n", "negado", "negada", "negados", "negadas", "niega", "ninguna", "ninguno", "neg", "negativo", "0", "false"}
SI = {"si", "s", "1", "positivo", "true", "x"}
SOSPECHA = ["probable", "sospecha", "a descartar", "posible", "en estudio", "descartar"]


def certeza_frase(frase: str, termino: str = "") -> str:
    f = normalizar(frase)
    for p in PSEUDO_NEGACION:
        f = f.replace(p, " ")
    corte = f.find(normalizar(termino)) if termino else -1
    previo = f[:corte] if corte > 0 else f
    if any(normalizar(n) in previo for n in NEGACION):
        return "negado"
    if any(s in previo for s in SOSPECHA):
        return "sospecha"
    return "afirmado"


def sujeto_frase(frase: str) -> str:
    f = normalizar(frase)
    return "familiar" if any(normalizar(x) in f for x in FAMILIAR) else "paciente"


def etiqueta(col: str, prefijo: str) -> str:
    base = col[len(prefijo):] if col.lower().startswith(prefijo.lower()) else col
    base = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base).replace("_", " ")
    return base.strip().capitalize()


class Libro:
    def __init__(self, expediente):
        self.expediente = str(expediente)
        self.hechos = []

    def agregar(self, tipo, valor, tabla, fila: Fila, campo, fecha=None, detalle=None,
                certeza="afirmado", sujeto="paciente", texto_fuente=None):
        valor = str(valor).strip()
        if not valor:
            return
        indice = fila.get("Indice") or "?"
        self.hechos.append({
            "expediente": fila.get("Expediente") or self.expediente,
            "tipo": tipo,
            "valor": valor,
            "detalle": {k: v for k, v in (detalle or {}).items() if v not in (None, "")},
            "fecha": fecha_iso(fecha),
            "ref": f"{tabla}#{indice}.{campo}",
            "refs_extra": [],
            "texto_fuente": (texto_fuente if texto_fuente is not None else valor)[:600],
            "certeza": certeza,
            "sujeto": sujeto,
            "tabla": tabla,
            "clave_ingreso": fila.get("ClaveIngreso"),
        })


def fecha_fila(tabla, f: Fila):
    for c in FECHA_TABLA.get(tabla, ["Fecha"]):
        d = parse_fecha(f.get(c))
        if d:
            return d
    return parse_fecha(f.get("Fecha"))


def _valor_campo_sn(v: str):
    n = normalizar(v)
    if n in NO or n.startswith("negad") or n.startswith("niega"):
        return "negado"
    if n in SI:
        return "si"
    return "texto"


def extraer(expediente, registros=None):
    reg = registros if registros is not None else registros_paciente(expediente)
    L = Libro(expediente)
    recetas_fecha = {}

    for tabla, df in reg.items():
        if df is None or df.empty:
            continue
        for _, s in df.iterrows():
            f = Fila(s)
            fecha = fecha_fila(tabla, f)

            # demográficos
            for campo in ("Sexo", "Edad"):
                v = f.get(campo)
                if v:
                    L.agregar("demografico", v, tabla, f, f.col(campo), fecha, {"campo": campo.lower()})

            # diagnósticos
            for c_cod, c_des in DIAGNOSTICOS.get(tabla, []):
                cod, des = f.get(c_cod), f.get(c_des)
                if cod or des:
                    L.agregar("diagnostico", des or cod, tabla, f, f.col(c_des) if des else f.col(c_cod), fecha,
                              {"cie10": cod, "sin_descripcion": "si" if cod and not des else "",
                               "sin_codigo": "si" if des and not cod else ""})

            # texto libre (para el LLM) + alergias ancladas al fragmento
            for campo in TEXTO_LIBRE.get(tabla, []):
                t = f.get(campo)
                if not t:
                    continue
                L.agregar("nota", t, tabla, f, f.col(campo), fecha, {"campo": campo})
                for frase, _pos in oraciones(t):
                    if "alerg" in normalizar(frase):
                        L.agregar("alergia", frase[:200], tabla, f, f.col(campo), fecha,
                                  {"origen": "texto libre"}, certeza_frase(frase, "alerg"), sujeto_frase(frase), frase)

            if tabla == "historiaclinica":
                for c, v in f.columnas("PP_"):
                    _antecedente(L, tabla, f, c, str(v), fecha, "PP_")
                for c, v in f.columnas("HF_"):
                    _antecedente(L, tabla, f, c, str(v), fecha, "HF_")
                for campo in ("Alcohol", "Fumador", "Cigarros", "Sustancias"):
                    v = f.get(campo)
                    if v:
                        est = _valor_campo_sn(v)
                        L.agregar("habito", f"{campo}: {v}", tabla, f, f.col(campo), fecha, {"habito": campo.lower()},
                                  "negado" if est == "negado" else certeza_frase(v))
                ts, rh = f.get("TipoSangre"), f.get("RH")
                if ts or rh:
                    L.agregar("tipo_sangre", f"{ts} {rh}".strip(), tabla, f, f.col("TipoSangre", "RH"), fecha,
                              {"grupo": ts, "rh": rh})
                for campo in ("Embarazos", "Partos", "Cesareas", "Abortos", "FUM"):
                    v = f.get(campo)
                    if v:
                        L.agregar("gineco", f"{campo}: {v}", tabla, f, f.col(campo), fecha, {"campo": campo.lower(), "n": numero(v)})

            elif tabla == "NotaMedicaUrg":
                motivo = f.get("MotivoConsulta") or f.get("Subjetivo")[:120]
                L.agregar("atencion", f"Urgencias: {motivo}" if motivo else "Atención en urgencias", tabla, f,
                          f.col("MotivoConsulta"), fecha, {"servicio": "urgencias", "triage": f.get("Triage"),
                                                           "destino": f.get("Destino")})

            elif tabla == "NotaIngreso_HC":
                L.agregar("atencion", f"Hospitalización: {f.get('MotivoIngreso') or f.get('DiagnosticoDesc') or 'ingreso'}",
                          tabla, f, f.col("MotivoIngreso"), fecha, {"servicio": "hospitalización", "pronostico": f.get("pronostico")})
                if f.get("EstudiosRealizados"):
                    L.agregar("estudio", f.get("EstudiosRealizados")[:400], tabla, f, f.col("EstudiosRealizados"), fecha)

            elif tabla == "notaegreso":
                fi = parse_fecha(f.get("FechaIngreso"))
                L.agregar("atencion", f"Egreso: {f.get('MotivoEgreso') or 'egreso hospitalario'}", tabla, f,
                          f.col("MotivoEgreso"), fecha, {"servicio": "egreso", "dias_estancia": f.get("DiasEstancia"),
                                                         "fecha_ingreso": fecha_iso(fi), "fecha_egreso": fecha_iso(fecha)})
                if f.get("MotivoDefuncion") or "defun" in normalizar(f.get("MotivoEgreso")):
                    L.agregar("defuncion", f.get("MotivoDefuncion") or f.get("MotivoEgreso"), tabla, f,
                              f.col("MotivoDefuncion", "MotivoEgreso"), fecha)

            elif tabla == "NotaPostOperatoria":
                op = f.get("descoper") or f.get("op_realizada") or f.get("descoperprog")
                if op:
                    L.agregar("procedimiento", op, tabla, f, f.col("descoper", "op_realizada", "descoperprog"), fecha,
                              {"diag_post": f.get("diagpostoper"), "complicaciones": f.get("complicaciones")})

            elif tabla == "hosdcr":
                d = f.get("Descripcion") or f.get("Cirugia")
                if d:
                    L.agregar("procedimiento", d, tabla, f, f.col("Descripcion", "Cirugia"), None, {"codigo": f.get("Cirugia")})

            elif tabla == "Recetas":
                if f.get("ClaveIngreso") and fecha:
                    recetas_fecha.setdefault(f.get("ClaveIngreso"), set()).add(fecha_iso(fecha))

            elif tabla == "Indicaciones":
                tipo_ind = normalizar(f.get("Tipo"))
                if any(x in tipo_ind for x in ("diet", "cuidad", "alimen", "enfer")):
                    continue
                nombre = f.get("Articulo", "Indicacion")
                if nombre:
                    L.agregar("medicamento", nombre, tabla, f, f.col("Articulo", "Indicacion"), fecha, {
                        "dosis": f"{f.get('Dosis')} {f.get('UdsDosis')}".strip() if f.get("Dosis") else "",
                        "via": f.get("Via"),
                        "frecuencia": f"{f.get('Frecuencia')} {f.get('UdsFrecuencia')}".strip() if f.get("Frecuencia") else "",
                        "estatus": f.get("Status"), "origen": "indicación hospitalaria"})

            elif tabla == "RecetasDet":
                nombre = f.get("Desc_Generica", "Descripcion", "Articulo")
                if nombre:
                    cada = f.get("Cada")
                    L.agregar("medicamento", nombre, tabla, f, f.col("Desc_Generica", "Descripcion", "Articulo"), None, {
                        "dosis": f"{f.get('Dosis')} {f.get('Dosis_Uds')}".strip() if f.get("Dosis") else "",
                        "via": f.get("Via"),
                        "frecuencia": f"cada {cada} {f.get('Cada_Uds')}".strip() if cada else "",
                        "duracion": f"{f.get('Durante')} {f.get('Durante_Uds')}".strip() if f.get("Durante") else "",
                        "origen": "receta"})

            elif tabla == "SignosVitales":
                for campo, (nom, uni, *_r) in SIGNOS.items():
                    v = numero(f.get(campo))
                    if v is not None and campo == "Talla" and v < 3:
                        v = round(v * 100, 1)  # venía en metros
                    if v is not None:
                        L.agregar("signo_vital", f"{nom}: {v:g} {uni}", tabla, f, f.col(campo), fecha,
                                  {"signo": campo, "num": v, "unidad": uni})
                sis, dia = numero(f.get("PA_NoInvasiva1")), numero(f.get("PA_NoInvasiva2"))
                if sis is not None and dia is not None:
                    L.agregar("signo_vital", f"Presión arterial: {sis:g}/{dia:g} mmHg", tabla, f, f.col("PA_NoInvasiva1"),
                              fecha, {"signo": "PA", "sis": sis, "dia": dia, "unidad": "mmHg"})

    # recetas: fecha desde el encabezado cuando es única para ese ingreso
    for h in L.hechos:
        if h["tabla"] == "RecetasDet" and not h["fecha"]:
            fechas = recetas_fecha.get(h["clave_ingreso"], set())
            if len(fechas) == 1:
                h["fecha"] = next(iter(fechas))
    return L.hechos


def _antecedente(L, tabla, f, col, v, fecha, prefijo):
    lab = etiqueta(col, prefijo)
    est = _valor_campo_sn(v)
    familiar = prefijo == "HF_"
    tipo = "antecedente_familiar" if familiar else "antecedente_personal"
    if "alerg" in col.lower() and not familiar:
        tipo = "alergia"
    if est == "negado":
        L.agregar(tipo, f"{lab}: {v}", tabla, f, col, fecha, {"campo": col}, "negado", "familiar" if familiar else "paciente")
    elif est == "si":
        L.agregar(tipo, lab, tabla, f, col, fecha, {"campo": col}, "afirmado", "familiar" if familiar else "paciente", f"{lab}: {v}")
    else:
        L.agregar(tipo, f"{lab}: {v}", tabla, f, col, fecha, {"campo": col}, certeza_frase(v),
                  "familiar" if familiar else "paciente")


def construir_expediente(expediente, fecha_cita=None, registros=None):
    """Hechos del paciente anteriores a la fecha de la cita, deduplicados y con ID."""
    from .dedup import deduplicar
    hechos = extraer(expediente, registros)
    if fecha_cita:
        corte = fecha_iso(parse_fecha(fecha_cita))
        hechos = [h for h in hechos if not h["fecha"] or h["fecha"] <= corte]
    hechos = deduplicar(hechos)
    hechos.sort(key=lambda h: (h["tipo"], h["fecha"] or ""), reverse=False)
    for i, h in enumerate(hechos, 1):
        h["id"] = f"H-{i:04d}"
    return hechos
