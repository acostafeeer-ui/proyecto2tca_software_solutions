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

# Campos de texto libre adicionales que trae el conjunto real de TCA
TEXTO_EXTRA = {"historiaclinica": ["PP_Observaciones", "HF_Observaciones", "CirugiasPrevias", "EstudiosLabyGab", "estudiosprevios"]}
OBSERVACIONES = {"pp_observaciones", "hf_observaciones"}

# Etiquetas legibles de las banderas S/N de historiaclinica
ETIQ_PP = {"quirurgico": "Antecedentes quirúrgicos", "transfusionales": "Antecedentes transfusionales",
           "endocrinas": "Enfermedades endocrinas", "hipertension": "Hipertensión arterial", "tumores": "Tumores",
           "diabetes": "Diabetes", "enfcongenitaspp": "Enfermedades congénitas", "enfcorazon": "Enfermedad del corazón",
           "enfhigado": "Enfermedad hepática", "enfriñon": "Enfermedad renal", "enfinfancia": "Enfermedades de la infancia",
           "traumaticos": "Antecedentes traumáticos", "otros": "Otros antecedentes personales"}
ETIQ_HF = {"diabeticos": "Diabetes", "hipertensivos": "Hipertensión", "oncologicos": "Cáncer",
           "enfcongenitas": "Enfermedades congénitas", "cardiologicos": "Cardiopatía", "nefropaticos": "Nefropatía",
           "otros": "Otros antecedentes familiares"}

# Códigos de hábitos del conjunto real (N/S/E/O)
HABITOS = {
    "fumador": {"n": ("Tabaquismo: niega", "negado"), "s": ("Tabaquismo: sí", "afirmado"), "e": ("Exfumador", "afirmado")},
    "alcohol": {"n": ("Consumo de alcohol: niega", "negado"), "s": ("Consumo de alcohol: sí", "afirmado"),
                "o": ("Consumo de alcohol: ocasional", "afirmado"), "e": ("Exconsumo de alcohol", "afirmado")},
    "sustancias": {"n": ("Consumo de sustancias: niega", "negado"), "s": ("Consumo de sustancias: sí", "afirmado"),
                   "e": ("Exconsumo de sustancias", "afirmado")},
}
SANGRE_NULA = {"se desconoce", "desconoce", "rh", "nd", "n/d", "desconocido", "no sabe"}

RX_ALERGIA = re.compile(r"\balergi(?:a|as)\b(?:\s+medicamentosas?)?\s*(?:a\s+|:|-|=)?\s*([^,;.\n]{0,80})", re.I)
RX_ALERGICO = re.compile(r"\bal[eé]rgic[oa]s?\s+a\s+([^,;.\n]{1,60})", re.I)
RX_ETIQUETA = re.compile(r"\s[A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}\s*:")
NEG_ALERGIA = ("negad", "niega", "ninguna", "ninguno", "sin ", "neg.", "(-)", "no ", "no,", "nada")


UNIDADES = {"hra": "horas", "hrs.": "horas", "hrs": "horas", "min": "minutos", "dia": "días", "día": "días",
            "sem.": "semanas", "mes": "meses"}
DIAG_NULO = {"no-def", "nodef", "no def", "0", "na"}


def unidad(u: str) -> str:
    return UNIDADES.get(normalizar(u), u)


def alergias_en_texto(t: str):
    """Extrae menciones de alergia de un texto: [(valor, certeza, fragmento)].

    Maneja los formatos reales de las notas: "ALERGIAS : NEGADAS", "alergias:-", "niega alergias",
    "alergia a penicilina", "ALERGIAS: PENICILINA QX: ..." (corta en la siguiente etiqueta).
    """
    out = []
    for m in RX_ALERGIA.finditer(t):
        crudo = m.group(1)
        corte = RX_ETIQUETA.search(" " + crudo)
        valor = (crudo[: corte.start()] if corte else crudo).strip(" -:=")
        previo = normalizar(t[max(0, m.start() - 30): m.start()])
        v = normalizar(valor)
        frag = t[max(0, m.start() - 15): m.end()].strip()
        if v.startswith(("no especificad", "aguda", "cutanea", "estacional")) or "desconoc" in v:
            continue
        cerca = previo[-22:]
        neg_previa = any(x in cerca for x in ("niega", "negad", "no refiere", "no se refiere", "sin ", "no ", "ningun", "descart"))
        if not v or neg_previa or any(v.startswith(n.strip()) or n in f" {v} " for n in NEG_ALERGIA):
            out.append(("Niega alergias", "negado", frag))
        else:
            out.append((f"Alergia: {valor}", "afirmado", frag))
    for m in RX_ALERGICO.finditer(t):
        out.append((f"Alergia: {m.group(1).strip()}", "afirmado", t[max(0, m.start() - 10): m.end()].strip()))
    return out


def edad_texto(v: str):
    """'31A' -> ('31 años', 31.0); '5M' -> ('5 meses', 0.42); '12D' -> ('12 días', 0.03)."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*([AaMmDdSs]?)", str(v))
    if not m:
        return v, None
    n, u = float(m.group(1)), m.group(2).upper()
    if u == "M":
        return f"{n:g} meses", n / 12
    if u == "D":
        return f"{n:g} días", n / 365
    if u == "S":
        return f"{n:g} semanas", n / 52
    return f"{n:g} años", n


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
            v = f.get("Sexo")
            if v:
                L.agregar("demografico", v, tabla, f, f.col("Sexo"), fecha, {"campo": "sexo"})
            v = f.get("Edad")
            if v:
                txt, anios = edad_texto(v)
                L.agregar("demografico", txt, tabla, f, f.col("Edad"), fecha, {"campo": "edad", "anios": anios}, texto_fuente=v)

            # diagnósticos
            for c_cod, c_des in DIAGNOSTICOS.get(tabla, []):
                cod, des = f.get(c_cod), f.get(c_des)
                cod = "" if normalizar(cod) in DIAG_NULO else cod
                des = "" if normalizar(des) in DIAG_NULO else des
                if cod or des:
                    L.agregar("diagnostico", des or cod, tabla, f, f.col(c_des) if des else f.col(c_cod), fecha,
                              {"cie10": cod, "sin_descripcion": "si" if cod and not des else "",
                               "sin_codigo": "si" if des and not cod else ""})

            # texto libre (para el LLM) + alergias ancladas al fragmento
            for campo in TEXTO_LIBRE.get(tabla, []) + TEXTO_EXTRA.get(tabla, []):
                t = f.get(campo)
                if not t or normalizar(t) in NO | {"na", "n/a", "negados"}:
                    continue
                L.agregar("nota", t, tabla, f, f.col(campo), fecha, {"campo": campo})
                for valor, cert, frag in alergias_en_texto(t):
                    sujeto = "familiar" if campo.lower() == "hf_observaciones" else sujeto_frase(frag)
                    L.agregar("alergia", valor, tabla, f, f.col(campo), fecha, {"origen": "texto libre"},
                              cert, sujeto, frag)

            if tabla == "historiaclinica":
                for c, v in f.columnas("PP_"):
                    if c.lower() not in OBSERVACIONES:
                        _antecedente(L, tabla, f, c, str(v), fecha, "PP_")
                for c, v in f.columnas("HF_"):
                    if c.lower() not in OBSERVACIONES:
                        _antecedente(L, tabla, f, c, str(v), fecha, "HF_")
                for campo in ("Alcohol", "Fumador", "Sustancias"):
                    v = f.get(campo)
                    if not v:
                        continue
                    codigo = HABITOS[campo.lower()].get(normalizar(v))
                    if codigo:
                        L.agregar("habito", codigo[0], tabla, f, f.col(campo), fecha, {"habito": campo.lower()},
                                  codigo[1], texto_fuente=f"{campo}: {v}")
                    else:
                        est = _valor_campo_sn(v)
                        L.agregar("habito", f"{campo}: {v}", tabla, f, f.col(campo), fecha, {"habito": campo.lower()},
                                  "negado" if est == "negado" else certeza_frase(v))
                cig = numero(f.get("Cigarros"))
                if cig:
                    L.agregar("habito", f"Cigarros: {cig:g}", tabla, f, f.col("Cigarros"), fecha, {"habito": "cigarros"})
                ts, rh = f.get("TipoSangre"), f.get("RH")
                ts = "" if normalizar(ts) in SANGRE_NULA else ts.upper()
                rh_n = normalizar(rh)
                rh = "+" if rh_n.startswith("posit") or rh == "+" else "-" if rh_n.startswith("negat") or rh == "-" else ""
                if ts:
                    L.agregar("tipo_sangre", f"{ts}{rh}", tabla, f, f.col("TipoSangre"), fecha,
                              {"grupo": ts, "rh": rh}, texto_fuente=f"{f.get('TipoSangre')} {f.get('RH')}".strip())
                for campo in ("Embarazos", "Partos", "Cesareas", "Abortos"):
                    n = numero(f.get(campo))
                    if n:
                        L.agregar("gineco", f"{campo}: {n:g}", tabla, f, f.col(campo), fecha, {"campo": campo.lower(), "n": n})
                fum = parse_fecha(f.get("FUM"))
                if fum:
                    L.agregar("gineco", f"FUM: {fecha_iso(fum)}", tabla, f, f.col("FUM"), fecha, {"campo": "fum"},
                              texto_fuente=f.get("FUM"))

            elif tabla == "NotaMedicaUrg":
                motivo = f.get("MotivoConsulta") or f.get("Subjetivo")[:120]
                L.agregar("atencion", f"Urgencias: {motivo}" if motivo else "Atención en urgencias", tabla, f,
                          f.col("MotivoConsulta"), fecha, {"servicio": "urgencias", "triage": f.get("Triage"),
                                                           "destino": f.get("Destino")})

            elif tabla == "NotaIngreso_HC":
                L.agregar("atencion", f"Hospitalización: {f.get('MotivoIngreso') or f.get('DiagnosticoDesc') or 'ingreso'}",
                          tabla, f, f.col("MotivoIngreso"), fecha, {"servicio": "hospitalización", "pronostico": f.get("pronostico")})
                if len(f.get("EstudiosRealizados")) >= 15 and "lo mencionado" not in normalizar(f.get("EstudiosRealizados")):
                    L.agregar("estudio", f.get("EstudiosRealizados")[:400], tabla, f, f.col("EstudiosRealizados"), fecha)

            elif tabla == "notaegreso":
                fi = parse_fecha(f.get("FechaIngreso"))
                L.agregar("atencion", f"Egreso: {f.get('MotivoEgreso') or 'egreso hospitalario'}", tabla, f,
                          f.col("MotivoEgreso"), fecha, {"servicio": "egreso", "dias_estancia": f.get("DiasEstancia"),
                                                         "fecha_ingreso": fecha_iso(fi), "fecha_egreso": fecha_iso(fecha)})
                md = f.get("MotivoDefuncion")
                md_valido = md and normalizar(md) not in NO | {"na", "n/a"} and len(md) > 3
                if normalizar(f.get("MotivoEgreso")).startswith("defun") or md_valido:
                    L.agregar("defuncion", md if md_valido else f.get("MotivoEgreso"), tabla, f,
                              f.col("MotivoDefuncion") if md_valido else f.col("MotivoEgreso"), fecha)

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
                if tipo_ind in ("1", "2") or any(x in tipo_ind for x in ("diet", "cuidad", "alimen", "enfer")):
                    continue  # dietas y cuidados generales
                articulo = f.get("Articulo")
                nombre = f.get("Descart") or (articulo if re.search(r"[A-Za-z]", articulo) else "") or \
                    (f.get("Indicacion") if re.search(r"[A-Za-z]", f.get("Indicacion")) else "")
                if not nombre:
                    continue
                campo_nombre = f.col("Descart") if f.get("Descart") else f.col("Articulo", "Indicacion")
                estatus = {"s": "suspendida", "c": "cancelada"}.get(normalizar(f.get("Status")), "")
                if tipo_ind == "e":
                    L.agregar("estudio", f"Estudio solicitado: {nombre}", tabla, f, campo_nombre, fecha,
                              {"estatus": estatus, "origen": "orden de laboratorio o gabinete"})
                    continue
                dosis = f.get("Dosis") if numero(f.get("Dosis")) else ""
                frec = f.get("Frecuencia") if numero(f.get("Frecuencia")) else ""
                cond = normalizar(f.get("Condiciones"))
                frecuencia = f"cada {frec} {unidad(f.get('UdsFrecuencia'))}".strip() if frec else \
                    ("dosis única" if "unica" in cond else "por razón necesaria" if "razon necesaria" in cond else "")
                L.agregar("medicamento", nombre, tabla, f, campo_nombre, fecha, {
                    "dosis": f"{dosis} {f.get('UdsDosis')}".strip() if dosis else "",
                    "via": f.get("Via"), "frecuencia": frecuencia, "estatus": estatus, "estatus_codigo": f.get("Status"),
                    "origen": "solución intravenosa" if tipo_ind == "s" else "indicación hospitalaria"})

            elif tabla == "RecetasDet":
                nombre = f.get("Desc_Generica", "Descripcion", "Articulo")
                if nombre:
                    cada = f.get("Cada")
                    L.agregar("medicamento", nombre, tabla, f, f.col("Desc_Generica", "Descripcion", "Articulo"), fecha, {
                        "dosis": f"{numero(f.get('Dosis')):g} {f.get('Dosis_Uds')}".strip() if numero(f.get("Dosis")) else "",
                        "via": f.get("Via"),
                        "frecuencia": f"cada {cada} {unidad(f.get('Cada_Uds'))}".strip() if numero(cada) else "",
                        "duracion": f"{f.get('Durante')} {unidad(f.get('Durante_Uds'))}".strip() if numero(f.get("Durante")) else "",
                        "origen": "receta"})

            elif tabla == "SignosVitales":
                for campo, (nom, uni, *_r) in SIGNOS.items():
                    v = numero(f.get(campo))
                    if not v:
                        continue  # 0 o vacío = no se midió
                    if campo == "Talla" and v < 3:
                        v = round(v * 100, 1)  # venía en metros
                    if v is not None:
                        L.agregar("signo_vital", f"{nom}: {v:g} {uni}", tabla, f, f.col(campo), fecha,
                                  {"signo": campo, "num": v, "unidad": uni})
                sis, dia = numero(f.get("PA_NoInvasiva1")), numero(f.get("PA_NoInvasiva2"))
                if sis and dia:
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
    familiar = prefijo == "HF_"
    clave = normalizar(col[len(prefijo):])
    lab = (ETIQ_HF if familiar else ETIQ_PP).get(clave) or etiqueta(col, prefijo)
    est = _valor_campo_sn(v)
    if est == "negado" and len(str(v).strip()) <= 2:
        return  # bandera "N": no aporta al resumen
    if est == "si" and familiar:
        lab = f"{lab} en familiares"
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
