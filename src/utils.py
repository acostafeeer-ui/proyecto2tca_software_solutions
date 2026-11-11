"""Funciones de apoyo: limpieza de texto, fechas y búsqueda de columnas."""
import re
import unicodedata
from datetime import datetime

import pandas as pd

from .config import FORMATOS_FECHA, NULOS


def es_nulo(v) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return str(v).strip().lower() in NULOS


def texto(v) -> str:
    """Devuelve el valor como texto limpio, o '' si es nulo."""
    if es_nulo(v):
        return ""
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return re.sub(r"\s+", " ", s)


def normalizar(s: str) -> str:
    """Minúsculas y sin acentos, para comparar."""
    s = unicodedata.normalize("NFKD", str(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


def parse_fecha(v):
    """Convierte texto a datetime probando varios formatos. Devuelve None si no se puede."""
    if es_nulo(v):
        return None
    if isinstance(v, (datetime, pd.Timestamp)):
        return pd.Timestamp(v).to_pydatetime()
    s = str(v).strip()
    for cand in (s, s[:19], s[:10]):
        for f in FORMATOS_FECHA:
            try:
                d = datetime.strptime(cand.strip(), f)
                if 1900 <= d.year <= 2100:
                    return d
            except ValueError:
                continue
    try:
        d = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.isna(d):
            return None
        return d.to_pydatetime()
    except Exception:
        return None


def fecha_iso(d) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


def numero(v):
    """Extrae un número de un texto ('36.5 °C' -> 36.5). None si no hay."""
    if es_nulo(v):
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


class Fila:
    """Acceso a columnas sin distinguir mayúsculas y minúsculas."""

    def __init__(self, serie: pd.Series):
        self._d = {str(k).lower(): v for k, v in serie.items()}
        self._orig = {str(k).lower(): str(k) for k in serie.index}

    def get(self, *nombres) -> str:
        for n in nombres:
            v = self._d.get(n.lower())
            if v is not None and not es_nulo(v):
                return texto(v)
        return ""

    def col(self, *nombres) -> str:
        """Nombre real de la primera columna que existe y tiene valor."""
        for n in nombres:
            v = self._d.get(n.lower())
            if v is not None and not es_nulo(v):
                return self._orig[n.lower()]
        return nombres[0]

    def columnas(self, prefijo: str):
        p = prefijo.lower()
        return [(self._orig[k], v) for k, v in self._d.items() if k.startswith(p) and not es_nulo(v)]


def oraciones(t: str):
    """Divide un texto en oraciones con su posición de inicio."""
    out, ini = [], 0
    for m in re.finditer(r"[^.;\n]+[.;\n]?", t):
        s = m.group(0).strip()
        if s:
            out.append((s, m.start()))
    return out
