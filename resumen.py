"""Genera el resumen de un paciente desde la línea de comandos.

Uso:
    python resumen.py <expediente> [--fecha AAAA-MM-DD] [--modo gemini|groq|plantilla]
"""
import argparse

from src.pipeline import generar_resumen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("expediente")
    ap.add_argument("--fecha", default=None)
    ap.add_argument("--modo", default="gemini")
    a = ap.parse_args()
    r = generar_resumen(a.expediente, a.fecha, a.modo)

    e = r["encabezado"]
    print(f"\nExpediente {r['expediente']}  |  {e['sexo']}  {e['edad']}  |  Sangre {e['tipo_sangre'] or '—'}  |  motor: {r['modo']}")
    print(f"Alergias: {r['alergias']['estado']}  {' '.join(r['alergias']['afirmadas'])}")
    print("\nALERTAS")
    for x in r["alertas"]:
        print(f"  [{x['severidad'].upper():5s}] {x['regla']}  {x['mensaje']}  {x['hechos'][:4]}")
    for s in r["secciones"]:
        if s["frases"]:
            print(f"\n{s['titulo'].upper()}")
            for f in s["frases"]:
                marca = " (reescrita)" if f["estado"] == "reescrita" else ""
                print(f"  - {f['texto']}  {f['refs']}{marca}")
    fid = r["fidelidad"]
    print(f"\nFidelidad: {fid['verificadas']} verificadas, {fid['reescritas']} reescritas, {fid['eliminadas']} eliminadas"
          f"  |  {r['estadisticas']['segundos']} s")
    print(f"JSON guardado en resultados/resumen_{r['expediente']}_{r['modo']}.json")


if __name__ == "__main__":
    main()
