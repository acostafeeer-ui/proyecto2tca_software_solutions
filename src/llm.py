"""Redacción con LLM (Gemini o Groq). El modelo solo recibe hechos de UN paciente y debe citar sus IDs."""
import json
import os
import re
import time

from dotenv import load_dotenv

from .config import MAX_CHARS_NOTA, MAX_NOTAS_LLM, SECCIONES

load_dotenv()

MODELO_GEMINI = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MODELO_GROQ = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

SISTEMA = """Eres un asistente que prepara a un médico antes de una consulta.
Recibes una lista de HECHOS de UN solo paciente. Cada hecho tiene un ID (H-0001, H-0002...).
Reglas obligatorias:
1. Usa únicamente los HECHOS. No agregues conocimiento médico, interpretaciones, recomendaciones ni diagnósticos nuevos.
2. Cada frase debe citar en "refs" los IDs de los hechos que la respaldan. Una frase sin refs no se mostrará.
3. Si un hecho tiene certeza "negado", no lo afirmes; puedes decir que se niega.
4. Si dos hechos se contradicen, no elijas uno: menciona ambos.
5. Conserva fechas, dosis, unidades y números exactamente como aparecen en el hecho.
6. Las NOTAS son texto libre del médico: puedes resumir de ellas datos clínicos relevantes (síntomas, estudios, resultados), citando el ID de la nota.
7. Frases cortas, en español, estilo clínico. Máximo 8 frases por sección. Si una sección no tiene hechos, devuélvela vacía.
8. Responde solo con JSON válido con esta forma:
{"secciones": [{"titulo": "<una de las secciones>", "frases": [{"texto": "...", "refs": ["H-0001"]}]}]}
Secciones permitidas: """ + "; ".join(SECCIONES) + "."


def _linea(h):
    det = {k: v for k, v in h["detalle"].items() if k not in ("num", "campo", "origen") and v}
    extra = f" | {json.dumps(det, ensure_ascii=False)}" if det else ""
    return f"{h['id']} | {h['tipo']} | {h['valor']} | fecha {h['fecha'] or 's/f'} | {h['certeza']} | {h['sujeto']}{extra}"


def contexto(hechos):
    """Selecciona y condensa lo que se envía al modelo (presupuesto de contexto)."""
    from .plantillas import _ultimos
    sel = []
    por = lambda t: [h for h in hechos if h["tipo"] == t]
    sel += por("demografico")[:4] + por("tipo_sangre") + por("alergia") + por("diagnostico")
    sel += por("antecedente_personal") + por("antecedente_familiar") + por("habito") + por("gineco")
    sel += por("procedimiento") + _ultimos(por("medicamento"), 40) + _ultimos(por("atencion"), 15)
    sel += por("estudio") + por("defuncion")
    sv = por("signo_vital")
    ult_por_signo = {}
    for h in _ultimos(sv, 500):
        ult_por_signo.setdefault(h["detalle"].get("signo"), h)
    sel += list(ult_por_signo.values())
    notas = _ultimos(por("nota"), MAX_NOTAS_LLM)
    lineas = [_linea(h) for h in sel]
    lineas_notas = [f"{n['id']} | NOTA {n['detalle'].get('campo','')} | fecha {n['fecha'] or 's/f'} | {n['valor'][:MAX_CHARS_NOTA]}" for n in notas]
    return "HECHOS:\n" + "\n".join(lineas) + "\n\nNOTAS:\n" + "\n".join(lineas_notas)


def _json(texto):
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?|```$", "", texto, flags=re.M).strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", texto, re.S)
        return json.loads(m.group(0)) if m else None


def llamar_gemini(prompt):
    from google import genai
    from google.genai import types
    cliente = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    r = cliente.models.generate_content(
        model=MODELO_GEMINI, contents=prompt,
        config=types.GenerateContentConfig(system_instruction=SISTEMA, temperature=0,
                                           response_mime_type="application/json"))
    return r.text


def llamar_groq(prompt):
    from groq import Groq
    cliente = Groq(api_key=os.environ["GROQ_API_KEY"])
    r = cliente.chat.completions.create(
        model=MODELO_GROQ, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SISTEMA}, {"role": "user", "content": prompt}])
    return r.choices[0].message.content


def disponible(proveedor):
    return bool(os.getenv("GEMINI_API_KEY" if proveedor == "gemini" else "GROQ_API_KEY"))


def resumir(hechos, proveedor="gemini"):
    """Devuelve (secciones, info). secciones = {titulo: [(texto, refs)]}; None si falla."""
    prompt = contexto(hechos)
    info = {"proveedor": proveedor, "caracteres_contexto": len(prompt), "intentos": 0, "error": ""}
    fn = llamar_gemini if proveedor == "gemini" else llamar_groq
    for intento in range(2):
        info["intentos"] = intento + 1
        try:
            datos = _json(fn(prompt))
            if datos and isinstance(datos.get("secciones"), list):
                out = {}
                for s in datos["secciones"]:
                    tit = s.get("titulo", "")
                    if tit not in SECCIONES:
                        continue
                    out[tit] = [(str(f.get("texto", "")).strip(), [str(r) for r in f.get("refs", [])])
                                for f in s.get("frases", []) if str(f.get("texto", "")).strip()]
                return out, info
        except Exception as e:  # red, límite de solicitudes, JSON inválido
            info["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            time.sleep(2)
    return None, info
