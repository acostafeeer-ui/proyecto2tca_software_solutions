"""Deduplicación: colapsa hechos repetidos conservando todas sus referencias."""
from rapidfuzz import fuzz

from .utils import normalizar

UMBRAL_CASI = 95  # similitud mínima (0-100) para considerar dos notas casi idénticas


SIN_FECHA = {"demografico", "tipo_sangre", "antecedente_personal", "antecedente_familiar", "alergia",
             "habito", "gineco", "diagnostico", "procedimiento"}


def _clave(h):
    det = h.get("detalle", {})
    extra = ""
    if h["tipo"] == "medicamento":
        extra = normalizar(f"{det.get('dosis','')}|{det.get('via','')}|{det.get('frecuencia','')}")
    if h["tipo"] == "signo_vital":
        extra = det.get("signo", "")
    fecha = "" if h["tipo"] in SIN_FECHA else h["fecha"]
    return (h["tipo"], normalizar(h["valor"]), fecha, h["certeza"], h["sujeto"], extra)


def deduplicar(hechos):
    estadistica = {"exactos": 0, "casi_identicos": 0}
    unicos = {}
    for h in hechos:
        k = _clave(h)
        if k in unicos:
            u = unicos[k]
            u["refs_extra"].append(h["ref"])
            fechas = [x for x in (u["fecha"], h["fecha"], u["detalle"].get("ultima_fecha", "")) if x]
            if fechas:
                u["fecha"], ultima = min(fechas), max(fechas)
                if ultima != u["fecha"]:
                    u["detalle"]["ultima_fecha"] = ultima
            estadistica["exactos"] += 1
        else:
            unicos[k] = h
    lista = list(unicos.values())

    # notas casi idénticas del mismo día (copy-forward)
    notas = [h for h in lista if h["tipo"] == "nota"]
    otras = [h for h in lista if h["tipo"] != "nota"]
    por_dia = {}
    for n in notas:
        por_dia.setdefault((n["fecha"], n["detalle"].get("campo", "")), []).append(n)
    finales = []
    for grupo in por_dia.values():
        conservadas = []
        for n in grupo:
            gemela = next((c for c in conservadas if fuzz.ratio(normalizar(c["valor"]), normalizar(n["valor"])) >= UMBRAL_CASI), None)
            if gemela:
                gemela["refs_extra"].append(n["ref"])
                estadistica["casi_identicos"] += 1
            else:
                conservadas.append(n)
        finales.extend(conservadas)
    resultado = otras + finales
    for h in resultado:
        h["refs_extra"] = sorted(set(h["refs_extra"]) - {h["ref"]})
    deduplicar.ultima_estadistica = estadistica
    return resultado


deduplicar.ultima_estadistica = {"exactos": 0, "casi_identicos": 0}
