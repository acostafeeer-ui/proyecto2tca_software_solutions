# Insight Clínico Verificable

Equipo Error 404 · X-RAIC 2026 · Track 2 (TCA Software Solutions)

Genera, al abrir una cita, un resumen del historial clínico del paciente donde cada frase cita el registro que la respalda (`Tabla#Indice.Campo`), y señala información faltante o contradictoria. Principio: la IA lee y redacta, el código verifica, el médico decide.

## Instalación (una vez)

```
python -m venv .venv
.venv\Scripts\activate            # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Windows   (Mac/Linux: cp .env.example .env)
```

Abre `.env` y pega tu llave de Gemini (https://aistudio.google.com/apikey) y, de respaldo, la de Groq (https://console.groq.com/keys).

## Uso

```
python ingest.py --parquet datos/      # carga los Parquet de TCA y crea expediente.duckdb
streamlit run app.py                   # abre la interfaz en el navegador
python eval.py --n 10 --modo gemini    # métricas
```

Sin los Parquet reales se puede probar todo con datos de prueba:

```
python generar_demo.py --salida datos_demo/ --pacientes 40
python ingest.py --parquet datos_demo/
streamlit run app.py
```

Generar un resumen desde la línea de comandos:

```
python resumen.py 100012 --fecha 2026-11-11 --modo gemini
```

## Estructura

| Archivo | Qué hace |
| --- | --- |
| `ingest.py` | Parquet → DuckDB: limpia nulos, quita columnas vacías, reporta fechas no convertibles |
| `src/datos.py` | Lee los registros de un paciente (siempre filtrando por Expediente) |
| `src/evidencia.py` | Convierte registros en hechos con referencia; detecta negación y antecedentes familiares |
| `src/dedup.py` | Colapsa duplicados exactos y notas casi idénticas conservando todas las referencias |
| `src/reglas.py` | 13 reglas: faltantes (F01–F05), contradicciones (C01–C07), duplicidad terapéutica (D01) |
| `src/llm.py` | Redacción con Gemini o Groq; el modelo debe citar el ID de cada hecho |
| `src/plantillas.py` | Resumen determinista sin LLM (respaldo y reescritura) |
| `src/verificador.py` | 5 comprobaciones por frase, incluida la de mismo paciente |
| `src/pipeline.py` | Orquesta todo y guarda el JSON en `resultados/` |
| `app.py` | Interfaz Streamlit: agenda, alergias, alertas, resumen, evidencia, modo auditor |
| `eval.py` | Métricas de la rúbrica e inyector de errores |
| `generar_demo.py` | Datos de prueba con las columnas del diccionario |

## Si los Parquet traen otros nombres de columna

Los nombres se buscan sin importar mayúsculas. Si alguna columna tiene un nombre distinto al del diccionario, se agrega en `src/config.py` (por ejemplo en `DIAGNOSTICOS`, `TEXTO_LIBRE` o `FECHA_TABLA`).

## Datos

La carpeta `datos/`, la base `expediente.duckdb` y el archivo `.env` están en `.gitignore`: no se suben al repositorio.
