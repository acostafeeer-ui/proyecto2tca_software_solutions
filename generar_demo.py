"""Genera Parquet de prueba con las columnas del diccionario de TCA.

Sirve para probar todo el sistema mientras no se tienen los datos reales.
Incluye errores sembrados a propósito (sexo distinto, alergia contradictoria, etc.).

Uso:
    python generar_demo.py --salida datos_demo/ --pacientes 40
    python ingest.py --parquet datos_demo/
"""
import argparse
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

DX = [("E11.9", "DIABETES MELLITUS TIPO 2 SIN COMPLICACIONES"), ("I10", "HIPERTENSION ARTERIAL SISTEMICA"),
      ("J18.9", "NEUMONIA NO ESPECIFICADA"), ("N39.0", "INFECCION DE VIAS URINARIAS"), ("K80.2", "COLELITIASIS"),
      ("J44.9", "ENFERMEDAD PULMONAR OBSTRUCTIVA CRONICA"), ("R10.4", "DOLOR ABDOMINAL"), ("R07.4", "DOLOR TORACICO")]
MEDS = [("METFORMINA", "850", "MG", "ORAL", "12", "HORAS"), ("LOSARTAN", "50", "MG", "ORAL", "24", "HORAS"),
        ("PARACETAMOL", "1", "G", "INTRAVENOSA", "8", "HORAS"), ("CEFTRIAXONA", "1", "G", "INTRAVENOSA", "12", "HORAS"),
        ("OMEPRAZOL", "40", "MG", "INTRAVENOSA", "24", "HORAS"), ("KETOROLACO", "30", "MG", "INTRAVENOSA", "8", "HORAS"),
        ("AMOXICILINA", "500", "MG", "ORAL", "8", "HORAS")]
MOTIVOS = ["DOLOR ABDOMINAL DE 2 DIAS DE EVOLUCION", "FIEBRE Y TOS PRODUCTIVA", "DOLOR TORACICO OPRESIVO",
           "DISURIA Y FIEBRE", "DESCONTROL GLUCEMICO", "CEFALEA INTENSA"]


def d2s(d):
    return d.strftime("%d/%m/%Y")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="datos_demo")
    ap.add_argument("--pacientes", type=int, default=40)
    ap.add_argument("--semilla", type=int, default=7)
    a = ap.parse_args()
    random.seed(a.semilla)
    out = Path(a.salida)
    out.mkdir(parents=True, exist_ok=True)
    T = {k: [] for k in ["historiaclinica", "NotaMedicaUrg", "NotaIngreso_HC", "NotasEvolucion", "NotaPostOperatoria",
                         "hosdcr", "Indicaciones", "Recetas", "RecetasDet", "notaegreso", "SignosVitales"]}
    idx = {k: 1000 for k in T}

    def nid(t):
        idx[t] += 1
        return str(idx[t])

    for p in range(a.pacientes):
        exp = f"{100000 + p}"
        sexo = random.choice(["F", "M"])
        edad0 = random.randint(25, 85)
        nombre = f"PACIENTE {p:03d}"
        base = date(2023, 1, 1) + timedelta(days=random.randint(0, 300))
        dxs = random.sample(DX[:6], 2)
        comun = lambda d, e=None: {"Expediente": exp, "Nombre": nombre, "Edad": str(e if e is not None else edad0 + (d.year - base.year)),
                                   "Sexo": sexo, "Fecha": d2s(d), "Hora": "10:00", "Usuario": "USR", "Medico": "M01",
                                   "NomMedico": "MEDICO ANONIMO", "Especialidad": "MEDICINA INTERNA"}
        alergia = random.choice(["PENICILINA", "NEGADAS", "SULFAS", ""])
        hc = {"Indice": nid("historiaclinica"), **comun(base), "ClaveIngreso": "",
              "Interrogatorio": f"PACIENTE {'FEMENINO' if sexo == 'F' else 'MASCULINO'} DE {edad0} AÑOS. "
                                + (f"REFIERE ALERGIA A {alergia}." if alergia not in ("NEGADAS", "") else ("NIEGA ALERGIAS." if alergia else "")),
              "MotivoConsulta": random.choice(MOTIVOS), "MedicamentosActuales": f"{dxs[0][1][:20]} EN TRATAMIENTO",
              "PP_Alergias": alergia, "PP_Quirurgicos": random.choice(["COLECISTECTOMIA 2019", "NEGADOS", "APENDICECTOMIA 2010"]),
              "PP_Transfusionales": "NEGADOS", "HF_Diabetes": random.choice(["MADRE", "NO", "PADRE"]), "HF_Hipertension": random.choice(["SI", "NO"]),
              "Alcohol": random.choice(["NEGADO", "OCASIONAL"]), "Fumador": random.choice(["NO", "SI"]), "Cigarros": "",
              "TipoSangre": random.choice(["O", "A", "B"]), "RH": "+",
              "Embarazos": "2" if sexo == "F" else "", "Partos": "2" if sexo == "F" else "", "Cesareas": "0" if sexo == "F" else "",
              "Abortos": "0" if sexo == "F" else "", "FUM": "",
              "Diagnostico1": dxs[0][0], "Desdiag1": dxs[0][1], "Diagnostico2": dxs[1][0], "Desdiag2": dxs[1][1],
              "ColumnaVacia1": None, "ColumnaVacia2": None}
        T["historiaclinica"].append(hc)

        for k in range(random.randint(1, 4)):
            d = base + timedelta(days=60 * (k + 1) + random.randint(0, 20))
            dx = random.choice(DX)
            T["NotaMedicaUrg"].append({"Indice": nid("NotaMedicaUrg"), **comun(d), "ClaveIngreso": "",
                                       "Triage": random.choice(["2", "3", "4"]), "MotivoConsulta": random.choice(MOTIVOS),
                                       "Subjetivo": "REFIERE DOLOR DE INTENSIDAD 7/10. " + ("NIEGA ALERGIAS." if alergia == "NEGADAS" else ""),
                                       "Objetivo": "CONSCIENTE, ORIENTADO, HIDRATADO.", "Apreciativo": dx[1],
                                       "Plan1": "ANALGESIA Y VIGILANCIA", "Destino": random.choice(["DOMICILIO", "HOSPITALIZACION"]),
                                       "Diag1": dx[0], "DesDiag1": dx[1]})
            for _ in range(2):
                T["SignosVitales"].append({"Indice": nid("SignosVitales"), **comun(d), "ClaveIngreso": "", "FechaAplica": d2s(d),
                                           "Temperatura": f"{random.uniform(36, 38.8):.1f}", "Pulso": str(random.randint(65, 110)),
                                           "PA_NoInvasiva1": str(random.randint(110, 150)), "PA_NoInvasiva2": str(random.randint(65, 95)),
                                           "Frecuencia": str(random.randint(14, 24)), "SatO2": str(random.randint(90, 99)),
                                           "Peso": f"{random.uniform(55, 98):.1f}", "Talla": f"{random.uniform(1.5, 1.85):.2f}",
                                           "GlucemiaCapilar": str(random.randint(90, 260))})

        if random.random() < 0.6:  # hospitalización
            clave = f"I{exp}{random.randint(10, 99)}"
            fi = base + timedelta(days=200)
            fe = fi + timedelta(days=random.randint(2, 7))
            dx = random.choice(DX)
            hosp = {"ClaveIngreso": clave, "FechaIngreso": d2s(fi), "Diagnostico": dx[0], "DiagnosticoDesc": dx[1], "Cama": "12", "Area": "MI"}
            T["NotaIngreso_HC"].append({"Indice": nid("NotaIngreso_HC"), **comun(fi), **hosp, "MotivoIngreso": random.choice(MOTIVOS),
                                        "Antecedentes": "DM2 DE 5 AÑOS DE EVOLUCION" if dxs[0][0] == "E11.9" else "SIN ANTECEDENTES DE IMPORTANCIA",
                                        "EstudiosRealizados": "BIOMETRIA HEMATICA: LEUCOCITOS 13,500. QUIMICA SANGUINEA: GLUCOSA 210 MG/DL.",
                                        "Diag1": dx[0], "desdiag1": dx[1], "pronostico": "BUENO"})
            for k in range((fe - fi).days):
                dk = fi + timedelta(days=k)
                texto = "PACIENTE ESTABLE, TOLERA VIA ORAL. SIN FIEBRE EN LAS ULTIMAS 24 HORAS."
                T["NotasEvolucion"].append({"Indice": nid("NotasEvolucion"), **comun(dk), **hosp, "Fecharegistro": d2s(dk),
                                            "Subjetivo": texto, "Objetivo": "SIGNOS VITALES ESTABLES", "Analisis": dx[1], "Plan1": "CONTINUAR MANEJO",
                                            "diag1": dx[0], "desdiag1": dx[1]})
            for m in random.sample(MEDS, 3):
                T["Indicaciones"].append({"Indice": nid("Indicaciones"), **comun(fi), **hosp, "Tipo": "MEDICAMENTO", "Articulo": m[0],
                                          "Dosis": m[1], "UdsDosis": m[2], "Via": m[3], "Frecuencia": m[4], "UdsFrecuencia": m[5],
                                          "Status": "ACTIVA"})
            T["Indicaciones"].append({"Indice": nid("Indicaciones"), **comun(fi), **hosp, "Tipo": "DIETA", "Indicacion": "DIETA BLANDA",
                                      "Status": "ACTIVA"})
            if random.random() < 0.4:
                T["NotaPostOperatoria"].append({"Indice": nid("NotaPostOperatoria"), **comun(fi + timedelta(days=1)), **hosp,
                                                "FechaCirugia": d2s(fi + timedelta(days=1)), "op_programada": "COLECISTECTOMIA",
                                                "descoper": "COLECISTECTOMIA LAPAROSCOPICA", "diagpreoper": "COLELITIASIS",
                                                "diagpostoper": "COLECISTITIS CRONICA LITIASICA", "complicaciones": "NINGUNA"})
                T["hosdcr"].append({"Indice": nid("hosdcr"), "ClaveIngreso": clave, "Consecutivo": "1", "Cirugia": "51.23",
                                    "Descripcion": "COLECISTECTOMIA LAPAROSCOPICA", "Tipo": "Q"})
            if random.random() < 0.85:
                T["notaegreso"].append({"Indice": nid("notaegreso"), **comun(fe), **hosp, "FechaEgreso": d2s(fe),
                                        "MotivoEgreso": "MEJORIA", "DiasEstancia": str((fe - fi).days),
                                        "Resumen": f"PACIENTE QUE INGRESA POR {dx[1]}, EVOLUCIONA A LA MEJORIA.",
                                        "Diag1": dx[0], "DescDiag1": dx[1]})
            T["Recetas"].append({"Indice": nid("Recetas"), **comun(fe), "ClaveIngreso": clave, "diag": dx[0], "desdiag": dx[1]})
            for m in random.sample(MEDS, 2):
                T["RecetasDet"].append({"Indice": nid("RecetasDet"), "ClaveIngreso": clave, "Articulo": m[0], "Desc_Generica": m[0],
                                        "Dosis": m[1], "Dosis_Uds": m[2], "Cada": m[4], "Cada_Uds": m[5], "Durante": "7",
                                        "Durante_Uds": "DIAS", "Via": m[3]})

        # errores sembrados en algunos pacientes
        r = random.random()
        if r < 0.12:  # sexo distinto
            T["NotaMedicaUrg"][-1]["Sexo"] = "M" if sexo == "F" else "F"
        elif r < 0.24:  # tipo de sangre distinto
            T["historiaclinica"].append({**hc, "Indice": nid("historiaclinica"), "TipoSangre": "AB", "RH": "-"})
        elif r < 0.36 and alergia == "PENICILINA" and T["NotaMedicaUrg"]:  # alergia contradictoria
            T["NotaMedicaUrg"][-1]["Subjetivo"] += " NIEGA ALERGIAS."
        elif r < 0.46:  # signo imposible
            T["SignosVitales"][-1]["SatO2"] = "140"
        elif r < 0.56 and T["Indicaciones"] and T["Indicaciones"][-2]["Expediente"] == exp:  # dosis faltante
            T["Indicaciones"][-2]["Dosis"] = None

    for t, filas in T.items():
        df = pd.DataFrame(filas).astype("string")
        df.to_parquet(out / f"{t}.parquet", index=False)
        print(f"  {t:20s} {len(df):>6} filas")


if __name__ == "__main__":
    main()
