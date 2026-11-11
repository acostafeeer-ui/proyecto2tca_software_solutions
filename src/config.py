"""Configuración central: rutas, tablas, columnas y umbrales.

Todos los nombres de columnas se buscan sin distinguir mayúsculas/minúsculas,
así que si en los Parquet reales una columna se llama "DESDIAG1" o "DesDiag1"
funciona igual. Si una columna tiene otro nombre, se agrega como alternativa aquí.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DB_PATH = RAIZ / "expediente.duckdb"
RESULTADOS = RAIZ / "resultados"

# Nombre canónico de cada tabla (como en el diccionario de TCA)
TABLAS = [
    "historiaclinica", "NotaMedicaUrg", "NotaIngreso_HC", "NotasEvolucion",
    "NotaPostOperatoria", "hosdcr", "Indicaciones", "Recetas", "RecetasDet",
    "notaegreso", "SignosVitales",
]

# Tablas que se ligan al paciente por ClaveIngreso (no tienen Expediente)
TABLAS_POR_INGRESO = ["hosdcr", "RecetasDet"]

# Valores que en realidad significan "vacío"
NULOS = {"", "-", "--", "n/a", "na", "nan", "none", "null", "s/d", "sd", ".", "nd", "0000-00-00"}

# Columnas con más de este porcentaje de nulos se descartan en la limpieza
UMBRAL_NULOS = 0.95

# Formatos de fecha que se prueban (las fechas vienen como texto)
FORMATOS_FECHA = [
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y", "%Y%m%d",
    "%d/%m/%y", "%m/%d/%Y",
]

# Diagnósticos: (columna código, columna descripción) por tabla
DIAGNOSTICOS = {
    "historiaclinica": [(f"Diagnostico{i}", f"Desdiag{i}") for i in range(1, 5)] + [("Diagnostico", "DiagnosticoDesc")],
    "NotaMedicaUrg": [(f"Diag{i}", f"DesDiag{i}") for i in range(1, 7)],
    "NotaIngreso_HC": [(f"Diag{i}", f"desdiag{i}") for i in range(1, 5)] + [("Diagnostico", "DiagnosticoDesc")],
    "NotasEvolucion": [(f"diag{i}", f"desdiag{i}") for i in range(1, 4)],
    "notaegreso": [(f"Diag{i}", f"DescDiag{i}") for i in range(1, 6)],
    "Recetas": [("diag", "desdiag")],
}

# Campos de texto libre por tabla (lo que lee el LLM y el extractor de alergias)
TEXTO_LIBRE = {
    "historiaclinica": ["Interrogatorio", "MotivoConsulta", "PadecimientoActual", "MedicamentosActuales", "AnalisisPlan"],
    "NotaMedicaUrg": ["MotivoConsulta", "Subjetivo", "Objetivo", "Apreciativo", "Plan1"],
    "NotaIngreso_HC": ["MotivoIngreso", "Antecedentes", "EstudiosRealizados", "TratamientoEmpleado", "Comentarios"],
    "NotasEvolucion": ["Subjetivo", "Objetivo", "Analisis", "Plan1"],
    "NotaPostOperatoria": ["hallazgos", "complicaciones", "descripcion"],
    "notaegreso": ["Resumen", "Manejo", "Problemas", "Recomendaciones"],
}

# Columna de fecha principal por tabla (la primera que exista)
FECHA_TABLA = {
    "historiaclinica": ["Fecha", "FechaIngreso"],
    "NotaMedicaUrg": ["Fecha", "LlegadaServicio"],
    "NotaIngreso_HC": ["FechaIngreso", "Fecha"],
    "NotasEvolucion": ["Fecharegistro", "Fecha"],
    "NotaPostOperatoria": ["FechaCirugia", "Fecha"],
    "Indicaciones": ["Fecha", "FechaInicio", "FechaIni"],
    "Recetas": ["Fecha"],
    "notaegreso": ["FechaEgreso", "Fecha"],
    "SignosVitales": ["FechaAplica", "Fecha"],
}

# Signos vitales: columna -> (etiqueta, unidad, mínimo posible, máximo posible, normal_bajo, normal_alto)
SIGNOS = {
    "Temperatura": ("Temperatura", "°C", 30, 45, 36.0, 37.5),
    "Pulso": ("Frecuencia cardiaca", "lpm", 20, 300, 60, 100),
    "Frecuencia": ("Frecuencia respiratoria", "rpm", 4, 80, 12, 20),
    "SatO2": ("Saturación de O2", "%", 40, 100, 92, 100),
    "Peso": ("Peso", "kg", 0.3, 350, None, None),
    "Talla": ("Talla", "cm", 30, 230, None, None),
    "GlucemiaCapilar": ("Glucosa capilar", "mg/dL", 10, 1500, 70, 180),
    "Dextrostix": ("Dextrostix", "mg/dL", 10, 1500, 70, 180),
}

# Clases de fármacos para cruzar con alergias (regla C05)
CLASES_FARMACOS = {
    "penicilinas": ["penicilina", "amoxicilina", "ampicilina", "dicloxacilina", "piperacilina", "bencilpenicilina", "oxacilina"],
    "cefalosporinas": ["cefalosporina", "ceftriaxona", "cefalexina", "cefuroxima", "cefotaxima", "cefepime", "cefazolina"],
    "sulfas": ["sulfa", "sulfametoxazol", "trimetoprim", "sulfadiazina"],
    "aine": ["aine", "ibuprofeno", "naproxeno", "diclofenaco", "ketorolaco", "metamizol", "aspirina",
             "acido acetilsalicilico", "ketoprofeno", "celecoxib", "indometacina", "piroxicam"],
    "opioides": ["opioide", "morfina", "tramadol", "codeina", "fentanilo", "buprenorfina", "oxicodona"],
    "quinolonas": ["quinolona", "ciprofloxacino", "levofloxacino", "moxifloxacino"],
    "macrolidos": ["macrolido", "azitromicina", "claritromicina", "eritromicina"],
}

# Disparadores de negación y de familiar (español clínico)
NEGACION = ["niega", "negado", "negada", "negativo", "sin ", "no refiere", "no presenta", "se descarta",
            "descartado", "ninguna", "ninguno", "no conocid", "no tiene", "(-)", "neg."]
FAMILIAR = ["madre", "padre", "mamá", "papá", "hermano", "hermana", "abuelo", "abuela", "tío", "tía",
            "hijo", "hija", "familiar", "hf:", "heredofamiliar"]
PSEUDO_NEGACION = ["sin embargo", "sin cambios", "no solo", "sin otro"]

# Presupuesto de contexto para el LLM
MAX_NOTAS_LLM = 10
MAX_CHARS_NOTA = 1200

# Problemas crónicos: prefijos CIE-10 (se comparan sin puntos ni espacios, en mayúsculas)
CIE10_CRONICOS = [
    "E10", "E11",                                # diabetes
    "I10", "I11", "I12", "I13", "I14", "I15",    # hipertensión
    "J44", "J45",                                # EPOC, asma
    "N18",                                       # enfermedad renal crónica
    "I25", "I50",                                # cardiopatía isquémica, insuficiencia cardiaca
    "E66",                                       # obesidad
    "E78",                                       # dislipidemia
    "C",                                         # cáncer
    "B20",                                       # VIH
    "K70", "K71", "K72", "K73", "K74",           # hepatopatía crónica
    "F",                                         # salud mental crónica
    "G40",                                       # epilepsia
    "E03",                                       # hipotiroidismo
]
# ...o descripción que contenga alguno de estos términos (sin acentos, palabra completa)
TERMINOS_CRONICOS = ["diabetes", "hipertension", "epoc", "asma", "insuficiencia renal cronica"]

SECCIONES = [
    "Problemas crónicos", "Diagnósticos previos", "Medicamentos recientes", "Antecedentes personales y quirúrgicos",
    "Antecedentes familiares", "Gineco-obstétricos", "Hábitos y factores de riesgo",
    "Últimas atenciones", "Estudios y signos vitales recientes",
]
