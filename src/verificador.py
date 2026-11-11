"""Verificador de fidelidad: cinco comprobaciones por frase antes de mostrarla al médico.

1. La frase cita al menos un hecho.
2. Cada hecho citado existe en el libro de evidencia.
3. Cada hecho citado pertenece al mismo Expediente (aislamiento entre pacientes).
4. Números y fármacos de la frase aparecen en los hechos citados.
5. La frase no afirma algo que la fuente niega.
Si falla 1-3: se elimina. Si falla 4-5: se reescribe con plantilla desde los hechos citados.
"""
import re

from .config import CLASES_FARMACOS
from .plantillas import frase_de
from .utils import normalizar

FARMACOS = sorted({p for ps in CLASES_FARMACOS.values() for p in ps if len(p) > 4}, key=len, reverse=True)
PALABRAS_NEG = ["niega", "negad", "sin ", "no ", "ningun", "descart"]
VACIAS = {"paciente", "registro", "registrado", "registrada", "documentado", "documentada", "desde", "ultimo", "ultima",
          "fecha", "presenta", "refiere", "antecedente", "antecedentes", "tiene", "cuenta", "sobre", "durante", "estatus",
          "activa", "activo", "horas", "cada", "entre", "segun", "nota", "notas", "consulta", "atencion"}


def _palabras(t):
    return {w for w in re.findall(r"[a-zñ]{5,}", normalizar(t)) if w not in VACIAS}


def _blob(hs):
    partes = []
    for h in hs:
        partes += [h["valor"], h["fecha"], h["texto_fuente"], h["detalle"].get("ultima_fecha", "")]
        partes += [str(v) for v in h["detalle"].values()]
    return normalizar(" ".join(partes))


def _numeros(t):
    return [n.replace(",", ".") for n in re.findall(r"\d+(?:[.,]\d+)?", t)]


def _num_en(n, blob):
    if n in blob:
        return True
    try:  # 36.50 vs 36.5
        f = float(n)
        return any(abs(float(x.replace(",", ".")) - f) < 1e-6 for x in re.findall(r"\d+(?:[.,]\d+)?", blob))
    except ValueError:
        return False


def verificar_frase(texto, refs, indice, expediente, calculada=False):
    """Devuelve (estado, texto_final, motivo). estado: verificada | reescrita | eliminada."""
    if not refs:
        return "eliminada", "", "sin referencias (comprobación 1)"
    faltan = [r for r in refs if r not in indice]
    if faltan:
        return "eliminada", "", f"cita hechos inexistentes {faltan} (comprobación 2)"
    citados = [indice[r] for r in refs]
    mismo = lambda a, b: str(a).strip().lstrip("0") == str(b).strip().lstrip("0")
    ajenos = [h["id"] for h in citados if not mismo(h["expediente"], expediente)]
    if ajenos:
        return "eliminada", "", f"INCIDENTE: cita hechos de otro paciente {ajenos} (comprobación 3)"
    if calculada:
        return "verificada", texto, ""
    blob = _blob(citados)
    t = re.sub(r"cie\s*-?\s*10", "cie", normalizar(texto))
    malos = [n for n in _numeros(t) if not _num_en(n, blob)]
    farm = [f for f in FARMACOS if f in t and f not in blob]
    if malos or farm:
        return "reescrita", " ".join(frase_de(h) for h in citados), f"datos no presentes en la fuente: {malos + farm} (comprobación 4)"
    clave_fuente = set().union(*(_palabras(h["valor"]) for h in citados)) if citados else set()
    if clave_fuente and not (_palabras(texto) & _palabras(" ".join(h["valor"] + " " + h["texto_fuente"] for h in citados))):
        return "reescrita", " ".join(frase_de(h) for h in citados), "la frase no corresponde a los hechos citados (comprobación 4)"
    negados = [h for h in citados if h["certeza"] == "negado"]
    dice_neg = any(p in f" {t} " for p in PALABRAS_NEG)
    if negados and len(negados) == len(citados) and not dice_neg:
        return "reescrita", " ".join(frase_de(h) for h in citados), "afirma algo que la fuente niega (comprobación 5)"
    return "verificada", texto, ""


def verificar(secciones, hechos, expediente):
    indice = {h["id"]: h for h in hechos}
    final, auditoria = {}, []
    cuenta = {"verificadas": 0, "reescritas": 0, "eliminadas": 0}
    for titulo, frases in secciones.items():
        final[titulo] = []
        for item in frases:
            texto, refs = item[0], item[1]
            calculada = len(item) > 2 and item[2] == "calculada"
            estado, txt, motivo = verificar_frase(texto, refs, indice, expediente, calculada)
            clave = {"verificada": "verificadas", "reescrita": "reescritas", "eliminada": "eliminadas"}[estado]
            cuenta[clave] += 1
            if estado != "verificada":
                auditoria.append({"seccion": titulo, "original": texto, "refs": refs, "estado": estado,
                                  "motivo": motivo, "final": txt})
            if estado != "eliminada":
                final[titulo].append({"texto": txt, "refs": [r for r in refs if r in indice], "estado": estado})
    return final, cuenta, auditoria
