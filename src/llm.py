"""Redacción con LLM (Gemini o Groq). El modelo solo recibe hechos de UN paciente y debe citar sus IDs."""
import json
import os
import re
import time

from dotenv import load_dotenv

from .config import (MAX_ATENCIONES_LLM, MAX_CHARS_NOTA, MAX_ESTUDIOS_LLM, MAX_MEDS_LLM, MAX_NOTAS_LLM,
                     SECCIONES)

load_dotenv()

MODELO_GEMINI = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MODELO_GROQ = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MODELO_GROQ_RESPALDO = os.getenv("GROQ_MODEL_RESPALDO", "qwen/qwen3.8-27b")
TIMEOUT_LLM_S = 45        # tiempo máximo total de la redacción con LLM (todos los intentos)
_MIN_RESTANTE_S = 5       # si queda menos que esto del presupuesto, no se intenta otra llamada

SISTEMA = """Eres un asistente que prepara a un médico antes de una consulta.
Recibes una lista de HECHOS de UN solo paciente, agrupados por tipo ([diagnostico], [medicamento]...). Cada hecho tiene un ID (H-0001, H-0002...).
Si un hecho no indica certeza, es afirmado; si no indica sujeto, se refiere al paciente.
Reglas obligatorias:
1. Usa únicamente los HECHOS. No agregues conocimiento médico, interpretaciones, recomendaciones ni diagnósticos nuevos.
2. Cada frase debe citar en "refs" los IDs de los hechos que la respaldan. Una frase sin refs no se mostrará.
3. Si un hecho tiene certeza "negado", no lo afirmes; puedes decir que se niega.
4. Si dos hechos se contradicen, no elijas uno: menciona ambos.
5. Conserva fechas, dosis, unidades y números exactamente como aparecen en el hecho.
6. Las NOTAS son texto libre del médico: puedes resumir de ellas datos clínicos relevantes (síntomas, estudios, resultados), citando el ID de la nota.
7. Frases cortas, en español, estilo clínico. Máximo 8 frases por sección. Si una sección no tiene hechos, devuélvela vacía.
8. Diagnósticos: los marcados "| crónico" van en "Problemas crónicos"; todos los demás van en "Diagnósticos previos", ordenados del más reciente al más antiguo y con su fecha. No muevas un diagnóstico de una sección a la otra.
9. SIGNOS VITALES: cada línea es un signo; cita el ID de esa misma línea y escribe el nombre, valor, unidad y fecha tal como aparecen (p. ej. "Saturación de O2: 98 % (2023-09-12)"). No los califiques ("estables", "normales").
10. Responde solo con JSON válido con esta forma:
{"secciones": [{"titulo": "<una de las secciones>", "frases": [{"texto": "...", "refs": ["H-0001"]}]}]}
Secciones permitidas: """ + "; ".join(SECCIONES) + "."


def _linea(h):
    """Línea compacta: ID | valor | fecha [| certeza si no es afirmado] [| sujeto si no es paciente] [| detalle]."""
    det = {k: v for k, v in h["detalle"].items() if k not in ("num", "campo", "origen", "estatus_codigo") and v}
    partes = [h["id"], h["valor"], f"fecha {h['fecha'] or 's/f'}"]
    if h["certeza"] != "afirmado":
        partes.append(h["certeza"])
    if h["sujeto"] != "paciente":
        partes.append(h["sujeto"])
    if det:
        partes.append("; ".join(f"{k}: {v}" for k, v in det.items()))
    if h["tipo"] == "diagnostico":
        from .plantillas import es_cronico
        if es_cronico(h):
            partes.append("crónico")
    return " | ".join(partes)


def _agrupar(hs):
    """Hechos bajo un encabezado por tipo (el tipo no se repite en cada línea)."""
    lineas, actual = [], None
    for h in hs:
        if h["tipo"] != actual:
            actual = h["tipo"]
            lineas.append(f"[{actual}]")
        lineas.append(_linea(h))
    return lineas


def contexto(hechos):
    """Selecciona y condensa lo que se envía al modelo (presupuesto de contexto)."""
    from .plantillas import _ultimos
    sel = []
    por = lambda t: [h for h in hechos if h["tipo"] == t]
    sel += por("demografico")[:4] + por("tipo_sangre") + por("alergia") + por("diagnostico")
    sel += por("antecedente_personal") + por("antecedente_familiar") + por("habito") + por("gineco")
    sel += (por("procedimiento") + _ultimos(por("medicamento"), MAX_MEDS_LLM)
            + _ultimos(por("atencion"), MAX_ATENCIONES_LLM))
    sel += _ultimos(por("estudio"), MAX_ESTUDIOS_LLM) + por("defuncion")
    sv = por("signo_vital")
    ult_por_signo = {}
    for h in _ultimos(sv, 500):
        ult_por_signo.setdefault(h["detalle"].get("signo"), h)
    notas = _ultimos(por("nota"), MAX_NOTAS_LLM)
    lineas = _agrupar(sel)
    # signos vitales en bloque propio: una línea por signo con su ID, nombre legible, valor, unidad y fecha
    # (sin el nombre interno de la columna, p. ej. "SatO2", que el modelo copiaba)
    lineas_sv = [f"{h['id']} | {h['valor']} | fecha {h['fecha'] or 's/f'} | cita {h['id']}" for h in ult_por_signo.values()]
    lineas_notas = [f"{n['id']} | NOTA {n['detalle'].get('campo','')} | fecha {n['fecha'] or 's/f'} | {n['valor'][:MAX_CHARS_NOTA]}" for n in notas]
    return ("HECHOS:\n" + "\n".join(lineas)
            + "\n\nSIGNOS VITALES (último valor de cada signo):\n" + "\n".join(lineas_sv)
            + "\n\nNOTAS:\n" + "\n".join(lineas_notas))


def _json(texto):
    texto = re.sub(r"<think>.*?</think>", "", texto or "", flags=re.S).strip()  # razonamiento de modelos tipo qwen
    texto = re.sub(r"^```(?:json)?|```$", "", texto, flags=re.M).strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", texto, re.S)
        return json.loads(m.group(0)) if m else None


def llamar_gemini(prompt):
    from google import genai
    from google.genai import types
    # timeout en milisegundos; sin reintentos del SDK (si falla, el pipeline usa la plantilla)
    cliente = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                           http_options=types.HttpOptions(timeout=TIMEOUT_LLM_S * 1000,
                                                          retry_options=types.HttpRetryOptions(attempts=1)))
    # razonamiento interno al mínimo: Gemini 2.5 acepta thinking_budget=0; gemini-3.8-flash rechaza MINIMAL,
    # así que se usa LOW (el nivel más bajo que acepta)
    if MODELO_GEMINI.startswith("gemini-2"):
        thinking = types.ThinkingConfig(thinking_budget=0)
    else:
        thinking = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    r = cliente.models.generate_content(
        model=MODELO_GEMINI, contents=prompt,
        config=types.GenerateContentConfig(system_instruction=SISTEMA, temperature=0,
                                           response_mime_type="application/json",
                                           thinking_config=thinking))
    return r.text


def llamar_groq(prompt, modelo=None, modo_json=True, timeout=TIMEOUT_LLM_S):
    """modo_json=False: sin response_format; la respuesta se parsea con _json() (tolera texto alrededor)."""
    from groq import Groq
    cliente = Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=0, timeout=timeout)  # sin reintentos ocultos del SDK
    extra = {"response_format": {"type": "json_object"}} if modo_json else {}
    r = cliente.chat.completions.create(
        model=modelo or MODELO_GROQ, temperature=0, **extra,
        messages=[{"role": "system", "content": SISTEMA}, {"role": "user", "content": prompt}])
    return r.choices[0].message.content or ""


def disponible(proveedor):
    return bool(os.getenv("GEMINI_API_KEY" if proveedor == "gemini" else "GROQ_API_KEY"))


def resumir(hechos, proveedor="gemini"):
    """Devuelve (secciones, info). secciones = {titulo: [(texto, refs)]}; None si falla."""
    prompt = contexto(hechos)
    info = {"proveedor": proveedor, "caracteres_contexto": len(prompt), "intentos": 0, "modelo": "", "error": "",
            "errores": []}
    # Gemini: un solo intento. Groq, solo si la respuesta no es JSON válido (json_validate_failed, JSON vacío o
    # con otra estructura): 1) modelo principal con response_format; 2) mismo modelo sin response_format,
    # parseado con _json(); 3) modelo de respaldo sin response_format. Timeout, 503, límite de solicitudes u
    # otro error -> se corta la cadena y el pipeline usa el modo plantilla. Todo dentro de TIMEOUT_LLM_S.
    if proveedor == "gemini":
        pasos = [(MODELO_GEMINI, lambda p, _m, _t: llamar_gemini(p))]
    else:
        pasos = [(MODELO_GROQ, lambda p, m, t: llamar_groq(p, m, True, t)),
                 (MODELO_GROQ, lambda p, m, t: llamar_groq(p, m, False, t)),
                 (MODELO_GROQ_RESPALDO, lambda p, m, t: llamar_groq(p, m, False, t))]
    limite = time.monotonic() + TIMEOUT_LLM_S
    for intento, (modelo, fn) in enumerate(pasos, start=1):
        restante = limite - time.monotonic()
        if restante < _MIN_RESTANTE_S:
            info["errores"].append(f"sin tiempo para el intento {intento} (quedaban {restante:.1f} s)")
            break
        info["intentos"], info["modelo"] = intento, modelo
        try:
            out = _secciones(_json(fn(prompt, modelo, restante)))
            if out is not None:
                info["error"] = ""
                return out, info
            info["error"] = "respuesta sin JSON válido con 'secciones'"
            json_invalido = True
        except Exception as e:  # red, límite de solicitudes, JSON inválido
            msg = str(e)
            info["error"] = f"{type(e).__name__}: {msg[:200]}"
            json_invalido = (isinstance(e, (json.JSONDecodeError, AttributeError, TypeError))
                             or any(x in msg for x in ("Failed to generate JSON", "Failed to validate JSON",
                                                       "json_validate_failed")))
        info["errores"].append(f"{intento} {modelo}: {info['error'][:120]}")
        if not json_invalido:
            break
    return None, info


def _secciones(datos):
    """JSON del modelo -> {titulo: [(texto, refs)]}; None si no tiene la forma esperada."""
    if not (isinstance(datos, dict) and isinstance(datos.get("secciones"), list)):
        return None
    out = {}
    for s in datos["secciones"]:
        tit = s.get("titulo", "")
        if tit not in SECCIONES:
            continue
        out[tit] = [(str(f.get("texto", "")).strip(), [str(r) for r in f.get("refs", [])])
                    for f in s.get("frases", []) if str(f.get("texto", "")).strip()]
    return out
