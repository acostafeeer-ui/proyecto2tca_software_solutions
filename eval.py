"""Evaluación con los criterios de la rúbrica.

Uso:
    python eval.py --n 10 --modo plantilla            # métricas + inyector de errores
    python eval.py --crear-referencias 10             # crea archivos para anotar a mano en eval/referencia/

Métricas:
    Criterio 1  cobertura contra la referencia anotada + ROUGE-L, BLEU, METEOR (si hay resumen de referencia)
    Criterio 2  recall del inyector de errores y alertas altas en pacientes sin modificar
    Criterio 3  % de frases con referencia válida
    Criterio 4  frases eliminadas o reescritas por el verificador (y revisión manual)
    Seguridad   referencias a otro paciente (debe ser 0)
"""
import argparse
import copy
import json
import statistics
from pathlib import Path

import pandas as pd

from src.config import RESULTADOS
from src.datos import agenda, registros_paciente
from src.evidencia import construir_expediente
from src.pipeline import generar_resumen
from src.reglas import evaluar
from src.utils import normalizar

REF_DIR = Path(__file__).parent / "eval" / "referencia"


# ---------------- inyector de errores ----------------
def _primera(reg, tabla):
    df = reg.get(tabla)
    return df if df is not None and len(df) else None


def _set(df, i, col, val):
    real = next((c for c in df.columns if c.lower() == col.lower()), None)
    if real is None:
        df[col] = None
        real = col
    df.loc[df.index[i], real] = val


def _get(df, i, col):
    real = next((c for c in df.columns if c.lower() == col.lower()), None)
    return None if real is None else df.loc[df.index[i], real]


def iny_sexo(reg):
    for t in ("NotaMedicaUrg", "SignosVitales", "NotasEvolucion", "historiaclinica"):
        df = _primera(reg, t)
        if df is not None:
            s = str(_get(df, -1, "Sexo") or "F").upper()[:1]
            _set(df, -1, "Sexo", "M" if s == "F" else "F")
            return True
    return False


def iny_sangre(reg):
    df = _primera(reg, "historiaclinica")
    if df is None:
        return False
    nueva = df.iloc[[-1]].copy()
    actual = str(_get(df, -1, "TipoSangre") or "")
    _set(nueva, 0, "TipoSangre", "AB" if actual != "AB" else "O")
    _set(nueva, 0, "RH", "-" if str(_get(df, -1, "RH") or "+") != "-" else "+")
    _set(nueva, 0, "Indice", "INY1")
    reg["historiaclinica"] = pd.concat([df, nueva], ignore_index=True)
    return True


def iny_alergia(reg):
    df = _primera(reg, "historiaclinica")
    urg = _primera(reg, "NotaMedicaUrg")
    if df is None or urg is None:
        return False
    _set(df, -1, "PP_Alergias", "PENICILINA")
    _set(urg, -1, "Subjetivo", str(_get(urg, -1, "Subjetivo") or "") + " NIEGA ALERGIAS.")
    return True


def iny_dosis(reg):
    df = _primera(reg, "Indicaciones")
    if df is None:
        return False
    _set(df, 0, "Dosis", None)
    _set(df, 0, "Status", "ACTIVA")
    return True


def iny_signo(reg):
    df = _primera(reg, "SignosVitales")
    if df is None:
        return False
    _set(df, -1, "SatO2", "140")
    return True


def iny_egreso(reg):
    df = _primera(reg, "notaegreso")
    if df is None:
        return False
    _set(df, -1, "FechaIngreso", "10/05/2024")
    _set(df, -1, "FechaEgreso", "01/05/2024")
    return True


INYECCIONES = {"C01 sexo distinto": (iny_sexo, "C01"), "C03 tipo de sangre distinto": (iny_sangre, "C03"),
               "C04 alergia contradictoria": (iny_alergia, "C04"), "F03 dosis faltante": (iny_dosis, "F03"),
               "C07 signo imposible": (iny_signo, "C07"), "C06 egreso antes de ingreso": (iny_egreso, "C06")}


def correr_inyector(expedientes, fecha):
    res = {k: {"probados": 0, "detectados": 0} for k in INYECCIONES}
    altas_limpios = []
    for exp in expedientes:
        reg = registros_paciente(exp)
        base = evaluar(construir_expediente(exp, fecha, copy.deepcopy(reg)))
        altas_limpios.append(sum(a["severidad"] == "alta" and a["regla"] != "F01" for a in base))
        conteo_base = {}
        for a in base:
            conteo_base[a["regla"]] = conteo_base.get(a["regla"], 0) + 1 + len(a["hechos"])
        for nombre, (fn, regla) in INYECCIONES.items():
            r2 = {k: (v.copy() if v is not None else v) for k, v in reg.items()}
            if not fn(r2):
                continue
            res[nombre]["probados"] += 1
            alertas = evaluar(construir_expediente(exp, fecha, r2))
            n = sum(1 + len(a["hechos"]) for a in alertas if a["regla"] == regla)
            if n > conteo_base.get(regla, 0):
                res[nombre]["detectados"] += 1
    return res, altas_limpios


# ---------------- cobertura y métricas de texto ----------------
def texto_resumen(r):
    return " ".join(f["texto"] for s in r["secciones"] for f in s["frases"])


def metricas_texto(pred, ref):
    out = {}
    try:
        from rouge_score import rouge_scorer
        out["ROUGE-L"] = rouge_scorer.RougeScorer(["rougeL"]).score(ref, pred)["rougeL"].fmeasure
    except Exception:
        pass
    try:
        import sacrebleu
        out["BLEU"] = sacrebleu.sentence_bleu(pred, [ref]).score / 100
    except Exception:
        pass
    try:
        from nltk.translate.meteor_score import meteor_score
        out["METEOR"] = meteor_score([ref.split()], pred.split())
    except Exception:
        pass
    return out


def crear_referencias(n, fecha, modo):
    REF_DIR.mkdir(parents=True, exist_ok=True)
    for exp in agenda(n)["expediente"]:
        r = generar_resumen(exp, fecha, modo, guardar=False)
        destino = REF_DIR / f"{exp}.json"
        if destino.exists():
            continue
        destino.write_text(json.dumps({
            "expediente": exp, "fecha_cita": fecha,
            "esperado": ["ESCRIBIR AQUÍ cada dato que DEBE aparecer, uno por elemento: diagnósticos, medicamentos, alergias..."],
            "resumen_referencia": "ESCRIBIR AQUÍ el resumen ideal redactado por el equipo.",
            "borrador_del_sistema": texto_resumen(r),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  creado", destino)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--modo", default="plantilla")
    ap.add_argument("--fecha", default=None, help="fecha de la cita (AAAA-MM-DD)")
    ap.add_argument("--crear-referencias", type=int, default=0)
    a = ap.parse_args()

    if a.crear_referencias:
        crear_referencias(a.crear_referencias, a.fecha, a.modo)
        return

    refs_anotadas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in REF_DIR.glob("*.json")} if REF_DIR.exists() else {}
    expedientes = list(dict.fromkeys(list(refs_anotadas) + list(agenda(a.n)["expediente"])))[: max(a.n, len(refs_anotadas))]

    filas, tiempos, ajenas, cobert, txt = [], [], 0, [], []
    for exp in expedientes:
        r = generar_resumen(exp, a.fecha, a.modo)
        frases = [f for s in r["secciones"] for f in s["frases"]]
        validas = sum(1 for f in frases if f["refs"] and all(x in r["evidencia"] for x in f["refs"]))
        ajenas += sum(1 for f in frases for x in f["refs"] if r["evidencia"].get(x, {}).get("expediente") != str(exp))
        tiempos.append(r["estadisticas"]["segundos"])
        filas.append({"expediente": exp, "frases": len(frases), "con_referencia_valida": validas,
                      **r["fidelidad"], "alertas": len(r["alertas"]), "segundos": r["estadisticas"]["segundos"]})
        ref = refs_anotadas.get(str(exp))
        if ref:
            esperados = [e for e in ref.get("esperado", []) if not e.startswith("ESCRIBIR")]
            if esperados:
                t = normalizar(texto_resumen(r))
                cobert.append(sum(normalizar(e) in t for e in esperados) / len(esperados))
            rr = ref.get("resumen_referencia", "")
            if rr and not rr.startswith("ESCRIBIR"):
                txt.append(metricas_texto(texto_resumen(r), rr))

    df = pd.DataFrame(filas)
    total_frases = int(df["frases"].sum()) if len(df) else 0
    iny, altas = correr_inyector(expedientes, a.fecha)
    probados = sum(v["probados"] for v in iny.values())
    detectados = sum(v["detectados"] for v in iny.values())

    m = {
        "pacientes": len(expedientes), "modo": a.modo,
        "criterio1_cobertura": round(statistics.mean(cobert), 3) if cobert else None,
        "criterio1_texto": {k: round(statistics.mean(d[k] for d in txt if k in d), 3) for k in ("ROUGE-L", "BLEU", "METEOR")
                            if any(k in d for d in txt)},
        "criterio2_recall_inyector": round(detectados / probados, 3) if probados else None,
        "criterio2_por_tipo": iny,
        "criterio2_alertas_altas_promedio_sin_modificar": round(statistics.mean(altas), 2) if altas else None,
        "criterio3_trazabilidad": round(df["con_referencia_valida"].sum() / total_frases, 3) if total_frases else None,
        "criterio4_eliminadas": int(df["eliminadas"].sum()) if len(df) else 0,
        "criterio4_reescritas": int(df["reescritas"].sum()) if len(df) else 0,
        "seguridad_referencias_otro_paciente": ajenas,
        "segundos_promedio": round(statistics.mean(tiempos), 2) if tiempos else None,
    }
    RESULTADOS.mkdir(exist_ok=True)
    (RESULTADOS / "metricas.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    df.to_csv(RESULTADOS / "metricas_por_paciente.csv", index=False)

    print(f"\nPacientes evaluados: {m['pacientes']}  (modo {a.modo})")
    print(f"Criterio 1  cobertura vs referencia: {m['criterio1_cobertura'] if m['criterio1_cobertura'] is not None else 'sin referencias anotadas'}")
    if m["criterio1_texto"]:
        print("            " + "  ".join(f"{k} {v}" for k, v in m["criterio1_texto"].items()))
    print(f"Criterio 2  recall inyector: {m['criterio2_recall_inyector']}  ({detectados}/{probados})")
    for k, v in iny.items():
        print(f"              {k:30s} {v['detectados']}/{v['probados']}")
    print(f"            alertas altas promedio en pacientes sin modificar: {m['criterio2_alertas_altas_promedio_sin_modificar']}")
    print(f"Criterio 3  trazabilidad: {m['criterio3_trazabilidad']}")
    print(f"Criterio 4  frases eliminadas: {m['criterio4_eliminadas']}  reescritas: {m['criterio4_reescritas']}")
    print(f"Seguridad   referencias a otro paciente: {ajenas}")
    print(f"Tiempo      promedio por resumen: {m['segundos_promedio']} s")
    print(f"\nGuardado en {RESULTADOS / 'metricas.json'}")


if __name__ == "__main__":
    main()
