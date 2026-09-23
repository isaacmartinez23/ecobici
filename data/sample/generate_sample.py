"""Generador de datos de muestra deterministas para ECOBICI.

Produce datos sintéticos pequeños pero realistas que permiten ejecutar TODO el
pipeline sin red ni descargas:

    data/sample/sample_trips.csv               (formato crudo ECOBICI)
    data/sample/sample_station_information.csv  (id, nombre, lat, lon, capacidad)
    data/sample/sample_station_status.csv       (serie temporal de disponibilidad)

Los datos son deterministas (semilla fija). Incluyen a propósito algunas filas
inválidas (duplicados, duración excesiva, estación ausente) para ejercitar las
reglas de limpieza. NO son datos reales: sirven para demostración y pruebas.

Uso:
    python -m data.sample.generate_sample
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

SEED = 42
TZ = ZoneInfo("America/Mexico_City")
N_STATIONS = 24
# Ventana fija (determinista, independiente de la fecha de hoy).
END_DATE = datetime(2025, 6, 29, 23, 59, tzinfo=TZ)
N_DAYS = 28
STATUS_DAYS = 2  # días finales con capturas de disponibilidad cada 5 min

OUT_DIR = Path(__file__).resolve().parent


def _stations(rng: np.random.Generator) -> pd.DataFrame:
    """Genera estaciones en una malla alrededor del centro de la CDMX."""
    lat0, lon0 = 19.42, -99.17
    ids = [str(i) for i in range(1, N_STATIONS + 1)]
    grid = int(np.ceil(np.sqrt(N_STATIONS)))
    rows = []
    for k, sid in enumerate(ids):
        r, c = divmod(k, grid)
        lat = lat0 + (r - grid / 2) * 0.006 + rng.normal(0, 0.0005)
        lon = lon0 + (c - grid / 2) * 0.006 + rng.normal(0, 0.0005)
        cap = int(rng.integers(15, 40))
        rows.append({"station_id": sid, "name": f"Estación {int(sid):02d}",
                     "lat": round(lat, 6), "lon": round(lon, 6), "capacity": cap})
    return pd.DataFrame(rows)


def _hour_profile(hour: int, weekend: bool) -> float:
    """Factor multiplicativo de demanda por hora del día."""
    if weekend:
        # Fin de semana: un solo pico suave por la tarde.
        return 0.3 + 0.9 * np.exp(-((hour - 14) ** 2) / 18)
    # Entre semana: picos de commute mañana y tarde.
    am = np.exp(-((hour - 8) ** 2) / 4)
    pm = np.exp(-((hour - 18) ** 2) / 5)
    return 0.15 + 1.2 * am + 1.3 * pm


def _generate_trips(stations: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Genera viajes con patrón hora/día y flujos hacia estaciones cercanas."""
    coords = stations.set_index("station_id")[["lat", "lon"]]
    ids = stations["station_id"].tolist()
    # Matriz de "atracción" inversa a la distancia para elegir destino.
    latlon = coords.to_numpy()
    dist = np.sqrt(((latlon[:, None, :] - latlon[None, :, :]) ** 2).sum(-1)) + 1e-6
    attract = 1.0 / dist
    np.fill_diagonal(attract, 0.0)
    attract = attract / attract.sum(1, keepdims=True)

    # Sesgo por estación: algunas generan más salidas (potenciales receptoras),
    # otras reciben más (potenciales donantes de bicis).
    out_bias = rng.uniform(0.6, 1.6, size=len(ids))

    records = []
    start_date = (END_DATE - timedelta(days=N_DAYS)).replace(hour=0, minute=0, second=0)
    for day in range(N_DAYS):
        d = start_date + timedelta(days=day)
        weekend = d.weekday() >= 5
        for hour in range(24):
            prof = _hour_profile(hour, weekend)
            for si, sid in enumerate(ids):
                lam = 1.1 * prof * out_bias[si]
                n = rng.poisson(lam)
                for _ in range(int(n)):
                    dest_idx = rng.choice(len(ids), p=attract[si])
                    dsid = ids[dest_idx]
                    minute = int(rng.integers(0, 60))
                    second = int(rng.integers(0, 60))
                    dep = d.replace(hour=hour, minute=minute, second=second)
                    dur = float(np.clip(rng.normal(14, 7), 3, 55))
                    arr = dep + timedelta(minutes=dur)
                    records.append(
                        {
                            "Genero_Usuario": rng.choice(["M", "F"], p=[0.62, 0.38]),
                            "Edad_Usuario": f"{int(np.clip(rng.normal(34, 10), 16, 80))}.0",
                            "Bici": f"{int(rng.integers(1000, 99999))}",
                            "Ciclo_Estacion_Retiro": sid,
                            "Fecha_Retiro": dep.strftime("%d/%m/%Y"),
                            "Hora_Retiro": dep.strftime("%H:%M:%S"),
                            "Ciclo_EstacionArribo": dsid,
                            "Fecha_Arribo": arr.strftime("%d/%m/%Y"),
                            "Hora_Arribo": arr.strftime("%H:%M:%S"),
                        }
                    )
    df = pd.DataFrame(records)

    # --- Inyecta filas inválidas para ejercitar las reglas de limpieza ---
    bad = []
    # 3 duplicados exactos de las primeras filas.
    bad.extend(df.head(3).to_dict("records"))
    # 2 con duración excesiva (>240 min).
    for r in df.head(2).to_dict("records"):
        r = dict(r)
        arr = datetime.strptime(f"{r['Fecha_Retiro']} {r['Hora_Retiro']}", "%d/%m/%Y %H:%M:%S") + timedelta(hours=5)
        r["Fecha_Arribo"] = arr.strftime("%d/%m/%Y")
        r["Hora_Arribo"] = arr.strftime("%H:%M:%S")
        bad.append(r)
    # 2 con estación de origen ausente.
    for r in df.head(2).to_dict("records"):
        r = dict(r)
        r["Ciclo_Estacion_Retiro"] = ""
        bad.append(r)
    df = pd.concat([df, pd.DataFrame(bad)], ignore_index=True)
    return df


def _generate_status(stations: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Genera capturas de disponibilidad cada 5 min para los últimos días."""
    rows = []
    start = (END_DATE - timedelta(days=STATUS_DAYS)).replace(minute=0, second=0, microsecond=0)
    steps = STATUS_DAYS * 24 * 12  # cada 5 min
    # Perfil por estación: algunas tienden a vaciarse, otras a llenarse.
    trend = rng.uniform(-0.35, 0.35, size=len(stations))
    for si, st in stations.reset_index(drop=True).iterrows():
        cap = int(st["capacity"])
        for k in range(steps):
            t_local = start + timedelta(minutes=5 * k)
            hour = t_local.hour + t_local.minute / 60
            # Nivel base con ciclo diario + tendencia + ruido.
            level = 0.5 + 0.35 * np.sin((hour - 6) / 24 * 2 * np.pi) + trend[si]
            level += rng.normal(0, 0.06)
            bikes = int(np.clip(round(level * cap), 0, cap))
            docks = cap - bikes
            t_utc = t_local.astimezone(ZoneInfo("UTC"))
            rows.append(
                {
                    "capture_id": f"{st['station_id']}|{int(t_utc.timestamp())}",
                    "station_id": st["station_id"],
                    "num_bikes_available": bikes,
                    "num_docks_available": docks,
                    "is_installed": True,
                    "is_renting": True,
                    "is_returning": True,
                    "last_reported": int(t_utc.timestamp()),
                    "captured_at_utc": t_utc.replace(tzinfo=None),
                    "captured_at_local": t_local.replace(tzinfo=None),
                    "ingested_at_utc": t_utc.replace(tzinfo=None),
                    "run_id": "sample",
                }
            )
    return pd.DataFrame(rows)


def generate() -> dict[str, Path]:
    rng = np.random.default_rng(SEED)
    stations = _stations(rng)
    trips = _generate_trips(stations, rng)
    status = _generate_status(stations, rng)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p_trips = OUT_DIR / "sample_trips.csv"
    p_info = OUT_DIR / "sample_station_information.csv"
    p_status = OUT_DIR / "sample_station_status.csv"
    trips.to_csv(p_trips, index=False)
    stations.to_csv(p_info, index=False)
    status.to_csv(p_status, index=False)
    print(f"Viajes de muestra:      {len(trips):>7d} filas -> {p_trips.name}")
    print(f"Estaciones de muestra:  {len(stations):>7d} filas -> {p_info.name}")
    print(f"Capturas de estado:     {len(status):>7d} filas -> {p_status.name}")
    return {"trips": p_trips, "info": p_info, "status": p_status}


if __name__ == "__main__":
    generate()
