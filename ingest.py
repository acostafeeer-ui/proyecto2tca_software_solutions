"""Carga los Parquet de TCA a DuckDB y los limpia.

Uso:
    python ingest.py --parquet datos/

Genera:
    expediente.duckdb          base de datos limpia
    resultados/reporte_limpieza.json   qué se hizo con cada tabla
"""
import argparse
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

from src.config import DB_PATH, NULOS, RESULTADOS, TABLAS, UMBRAL_NULOS, FECHA_TABLA
from src.utils import parse_fecha


def nombre_canonico(archivo: Path):
    base = archivo.stem.lower().replace("-", "_").replace(" ", "")
    for t in TABLAS:
        if base == t.lower():
            return t
    for t in sorted(TABLAS, key=len, reverse=True):
        if t.lower() in base:
            return t
    return None


def limpiar(df: pd.DataFrame, tabla: str):
    rep = {"filas": len(df), "columnas_originales": df.shape[1]}
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    # todo a texto (las fechas vienen como texto; así no se pierde nada)
    for c in df.columns:
        s = df[c].astype("string").str.strip()
        s = s.where(~s.str.lower().isin(NULOS), None)
        s = s.str.replace(r"^(\d+)\.0$", r"\1", regex=True)
        df[c] = s
    # columnas casi vacías
    proporcion = df.isna().mean()
    claves = {"indice", "expediente", "claveingreso", "sexo", "edad", "fecha"}
    quitar = [c for c, p in proporcion.items() if p > UMBRAL_NULOS and c.lower() not in claves]
    df = df.drop(columns=quitar)
    rep["columnas_quitadas"] = len(quitar)
    rep["columnas_finales"] = df.shape[1]
    # índice: si no existe, se crea uno para poder citar el registro
    if not any(c.lower() == "indice" for c in df.columns):
        df.insert(0, "Indice", [str(i + 1) for i in range(len(df))])
        rep["indice_generado"] = True
    # tasa de fechas que no se pudieron convertir
    for c in FECHA_TABLA.get(tabla, []):
        real = next((x for x in df.columns if x.lower() == c.lower()), None)
        if real:
            muestra = df[real].dropna().head(2000)
            if len(muestra):
                malas = sum(parse_fecha(v) is None for v in muestra)
                rep[f"fechas_no_convertidas_{real}"] = round(malas / len(muestra), 4)
            break
    return df, rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="datos", help="carpeta con los .parquet")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()

    carpeta = Path(args.parquet)
    archivos = sorted(carpeta.rglob("*.parquet"))
    if not archivos:
        sys.exit(f"No encontré archivos .parquet en {carpeta.resolve()}")

    RESULTADOS.mkdir(exist_ok=True)
    Path(args.db).unlink(missing_ok=True)
    con = duckdb.connect(args.db)
    reporte = {}
    for a in archivos:
        tabla = nombre_canonico(a)
        if not tabla:
            print(f"  [omitido] {a.name}: no corresponde a ninguna tabla del diccionario")
            continue
        df = pd.read_parquet(a)
        df, rep = limpiar(df, tabla)
        if tabla in reporte:  # tabla partida en varios archivos
            previo = con.execute(f'SELECT * FROM "{tabla}"').df()
            df = pd.concat([previo, df], ignore_index=True)
            con.execute(f'DROP TABLE "{tabla}"')
        con.register("tmp_df", df)
        con.execute(f'CREATE TABLE "{tabla}" AS SELECT * FROM tmp_df')
        con.unregister("tmp_df")
        reporte[tabla] = rep
        print(f"  {tabla:20s} {rep['filas']:>8,} filas  {rep['columnas_finales']:>4} columnas "
              f"({rep['columnas_quitadas']} vacías quitadas)")

    faltan = [t for t in TABLAS if t not in reporte]
    if faltan:
        print("  Tablas no encontradas:", ", ".join(faltan))
    reporte["_faltantes"] = faltan
    (RESULTADOS / "reporte_limpieza.json").write_text(json.dumps(reporte, indent=2, ensure_ascii=False), encoding="utf-8")
    con.close()
    print(f"\nBase lista: {args.db}")


if __name__ == "__main__":
    main()
