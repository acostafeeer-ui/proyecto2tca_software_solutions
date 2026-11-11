"""Pipeline completo: expediente + fecha de cita -> resumen verificado (JSON)."""
import json
import time
from datetime import datetime

from .config import RESULTADOS, SECCIONES
from .dedup import deduplicar
from .evidencia import construir_expediente
from .llm import disponible, resumir
from .plantillas import calcular_imc, encabezado, estado_alergias, secciones_plantilla
from .reglas import evaluar
from .verificador import verificar


def generar_resumen(expediente, fecha_cita=None, modo="gemini", registros=None, guardar=True):
    """modo: 'gemini', 'groq' o 'plantilla' (sin LLM)."""
    t0 = time.time()
    fecha_cita = fecha_cita or datetime.now().strftime("%Y-%m-%d")
    hechos = construir_expediente(expediente, fecha_cita, registros)
    dedup_stats = dict(deduplicar.ultima_estadistica)
    alertas = evaluar(hechos)
    base = secciones_plantilla(hechos)

    modo_real, info_llm = "plantilla", {}
    secciones = base
    if modo in ("gemini", "groq") and disponible(modo):
        borrador, info_llm = resumir(hechos, modo)
        if borrador is not None:
            modo_real = modo
            secciones = {}
            for s in SECCIONES:
                frases = borrador.get(s) or []
                secciones[s] = frases if frases else base.get(s, [])  # completa secciones vacías con plantilla
            imc = calcular_imc(hechos)
            if imc and not any("imc" in f[0].lower() for f in secciones["Hábitos y factores de riesgo"]):
                secciones["Hábitos y factores de riesgo"].append(imc)
    elif modo in ("gemini", "groq"):
        info_llm = {"error": f"sin llave de API para {modo}; se usó el modo plantilla"}

    final, fidelidad, auditoria = verificar(secciones, hechos, expediente)
    indice = {h["id"]: h for h in hechos}
    resultado = {
        "expediente": str(expediente),
        "fecha_cita": fecha_cita,
        "generado": datetime.now().isoformat(timespec="seconds"),
        "modo": modo_real,
        "encabezado": encabezado(hechos),
        "alergias": estado_alergias(hechos),
        "alertas": alertas,
        "secciones": [{"titulo": s, "frases": final.get(s, [])} for s in SECCIONES],
        "fidelidad": fidelidad,
        "auditoria": auditoria,
        "estadisticas": {
            "hechos": len(hechos),
            "registros_fuente": sum(1 + len(h["refs_extra"]) for h in hechos),
            "duplicados_colapsados": dedup_stats.get("exactos", 0) + dedup_stats.get("casi_identicos", 0),
            "segundos": round(time.time() - t0, 2),
            "llm": info_llm,
        },
        # referencias legibles para cada ID citado (panel de evidencia)
        "evidencia": {i: {"ref": h["ref"], "refs_extra": h["refs_extra"][:20], "tipo": h["tipo"], "valor": h["valor"],
                          "fecha": h["fecha"], "texto_fuente": h["texto_fuente"], "certeza": h["certeza"],
                          "expediente": h["expediente"]}
                      for i, h in indice.items()},
    }
    if guardar:
        RESULTADOS.mkdir(exist_ok=True)
        (RESULTADOS / f"resumen_{expediente}_{modo_real}.json").write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    return resultado
