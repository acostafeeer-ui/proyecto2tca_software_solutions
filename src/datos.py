"""Lectura de la base por paciente. Toda consulta filtra por Expediente (capa 1 de aislamiento)."""
from functools import lru_cache

import duckdb
import pandas as pd

from .config import DB_PATH, TABLAS, TABLAS_POR_INGRESO
from .utils import es_nulo


@lru_cache(maxsize=1)
def conexion(path: str = str(DB_PATH)):
    return duckdb.connect(path, read_only=True)


def tablas_existentes(con):
    nombres = {r[0].lower(): r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    return {t: nombres[t.lower()] for t in TABLAS if t.lower() in nombres}


def _col(con, tabla_real, nombre):
    cols = [r[0] for r in con.execute(f'DESCRIBE "{tabla_real}"').fetchall()]
    return next((c for c in cols if c.lower() == nombre.lower()), None)


def claves_validas(valores):
    """ClaveIngreso vacías o '0' se descartan: unirían registros de otros pacientes."""
    return sorted({str(v).strip() for v in valores if not es_nulo(v) and str(v).strip() not in {"0", "00", "-1"}})


def registros_paciente(expediente: str, con=None) -> dict:
    """Devuelve {tabla: DataFrame} con todos los registros de un paciente."""
    con = con or conexion()
    existentes = tablas_existentes(con)
    out, claves = {}, set()
    for t, real in existentes.items():
        if t in TABLAS_POR_INGRESO:
            continue
        c_exp = _col(con, real, "Expediente")
        if not c_exp:
            continue
        # se compara sin ceros a la izquierda: "00000000000010269632" y "10269632" son el mismo expediente
        df = con.execute(f'SELECT * FROM "{real}" WHERE LTRIM(TRIM(CAST("{c_exp}" AS VARCHAR)), \'0\') = LTRIM(?, \'0\')',
                         [str(expediente).strip()]).df()
        out[t] = df
        c_ing = _col(con, real, "ClaveIngreso")
        if c_ing and len(df):
            claves.update(claves_validas(df[c_ing]))
    claves = sorted(claves)
    for t in TABLAS_POR_INGRESO:
        real = existentes.get(t)
        if not real or not claves:
            out[t] = pd.DataFrame()
            continue
        c_ing = _col(con, real, "ClaveIngreso")
        if not c_ing:
            out[t] = pd.DataFrame()
            continue
        marcas = ",".join(["?"] * len(claves))
        out[t] = con.execute(f'SELECT * FROM "{real}" WHERE TRIM(CAST("{c_ing}" AS VARCHAR)) IN ({marcas})', claves).df()
    return out


def agenda(n: int = 30, con=None) -> pd.DataFrame:
    """Pacientes para la agenda simulada: los que tienen historia clínica y más registros."""
    con = con or conexion()
    existentes = tablas_existentes(con)
    partes = []
    for t, real in existentes.items():
        c_exp = _col(con, real, "Expediente")
        if c_exp:
            partes.append(f'SELECT TRIM(CAST("{c_exp}" AS VARCHAR)) AS exp, \'{t}\' AS tabla FROM "{real}"')
    if not partes:
        return pd.DataFrame(columns=["expediente", "registros", "tablas"])
    q = (f"SELECT exp AS expediente, COUNT(*) AS registros, COUNT(DISTINCT tabla) AS tablas "
         f"FROM ({' UNION ALL '.join(partes)}) WHERE exp IS NOT NULL AND exp <> '' "
         f"GROUP BY exp ORDER BY tablas DESC, registros DESC LIMIT {int(n)}")
    return con.execute(q).df()
