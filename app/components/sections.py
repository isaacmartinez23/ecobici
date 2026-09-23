"""Secciones de la app Streamlit de ECOBICI (en español)."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

from app.utils import data

DOW_NOMBRES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


# --------------------------------------------------------------------------- #
def render_resumen() -> None:
    st.header("Resumen ejecutivo")
    s = data.summary()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Viajes válidos", f"{s['n_trips']:,}")
    c2.metric("Estaciones", s["n_stations"])
    c3.metric("Registros descartados", f"{s['pct_rejected']}%")
    periodo = "—"
    if s["period_min"] is not None:
        periodo = f"{pd.Timestamp(s['period_min']).date()} → {pd.Timestamp(s['period_max']).date()}"
    c4.metric("Periodo analizado", periodo)

    st.subheader("Línea base vs. modelo (partición de prueba)")
    if s["mae_base"] is not None:
        cola, colb, colc = st.columns(3)
        cola.metric("MAE línea base", f"{s['mae_base']:.3f}")
        colb.metric("MAE modelo", f"{s['mae_model']:.3f}")
        mejora = 100 * (s["mae_base"] - s["mae_model"]) / s["mae_base"] if s["mae_base"] else 0
        colc.metric("Mejora del modelo", f"{mejora:.1f}%",
                    help="Positivo = el modelo reduce el error respecto a la línea base.")
    else:
        st.info("Aún no hay métricas de modelo. Ejecuta el entrenamiento y la evaluación.")

    st.subheader("Estaciones con mayor riesgo de vaciado")
    risk = data.stations_risk()
    if not risk.empty:
        top = risk.head(10)[["station_id", "name", "demanda_media", "riesgo_vaciado", "min_sin_bicis"]]
        top = top.rename(columns={
            "station_id": "ID", "name": "Estación", "demanda_media": "Demanda media (salidas/h)",
            "riesgo_vaciado": "Riesgo vaciado", "min_sin_bicis": "Min. sin bicis",
        })
        st.dataframe(top, hide_index=True, width="stretch")
    else:
        st.info("Sin datos de disponibilidad para calcular riesgo.")


# --------------------------------------------------------------------------- #
def render_mapa() -> None:
    st.header("Mapa interactivo")
    st.caption("Color por riesgo de vaciado (rojo = alto), tamaño por demanda media.")

    dows_sel = st.multiselect(
        "Días de la semana", options=list(range(7)),
        default=list(range(5)), format_func=lambda i: DOW_NOMBRES[i],
    )
    hour = st.slider("Hora del día", 0, 23, 18)
    min_risk = st.slider("Riesgo mínimo a mostrar", 0.0, 1.0, 0.0, 0.05)

    df = data.stations_risk_filtered(dows_sel, hour)
    if df.empty:
        st.info("No hay estaciones para mostrar. Ejecuta el pipeline con datos.")
        return
    df = df[df["riesgo_vaciado"] >= min_risk].copy()
    if df.empty:
        st.warning("Ninguna estación supera el umbral de riesgo seleccionado.")
        return

    df["r"] = (255 * df["riesgo_vaciado"]).clip(0, 255)
    df["g"] = (200 * (1 - df["riesgo_vaciado"])).clip(0, 255)
    df["radio"] = 40 + df["demanda_media"] * 25

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=df,
        get_position="[lon, lat]",
        get_fill_color="[r, g, 60, 180]",
        get_radius="radio",
        pickable=True,
    )
    view = pdk.ViewState(latitude=float(df["lat"].mean()), longitude=float(df["lon"].mean()),
                         zoom=12, pitch=0)
    tooltip = {"html": "<b>{name}</b><br/>Riesgo vaciado: {riesgo_vaciado}<br/>"
                        "Demanda media: {demanda_media}", "style": {"color": "white"}}
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip=tooltip,
                             map_style=None))
    st.caption(f"{len(df)} estaciones mostradas para {', '.join(DOW_NOMBRES[i] for i in dows_sel) or '—'} "
               f"a las {hour}:00 h.")


# --------------------------------------------------------------------------- #
def render_demanda() -> None:
    st.header("Demanda por estación")
    estaciones = data.station_list()
    if not estaciones:
        st.info("No hay datos de demanda. Ejecuta el pipeline.")
        return
    est = st.selectbox("Estación", estaciones)

    perfil = data.demand_profile(est)
    if not perfil.empty:
        fig = go.Figure()
        fig.add_bar(x=perfil["hour"], y=perfil["salidas"], name="Salidas")
        fig.add_bar(x=perfil["hour"], y=perfil["llegadas"], name="Llegadas")
        fig.add_scatter(x=perfil["hour"], y=perfil["flujo_neto"], name="Flujo neto",
                        mode="lines+markers", line={"color": "black"})
        fig.update_layout(barmode="group", title="Perfil horario promedio",
                          xaxis_title="Hora", yaxis_title="Viajes/hora", height=380)
        st.plotly_chart(fig, width="stretch")

    ts = data.demand_timeseries(est)
    if not ts.empty:
        st.subheader("Observado vs. predicción")
        fig2 = px.line(ts, x="ts", y=["observado", "linea_base", "modelo"],
                       labels={"value": "salidas/hora", "ts": "tiempo", "variable": "serie"})
        fig2.update_layout(height=380)
        st.plotly_chart(fig2, width="stretch")
        st.caption("La incertidumbre no se modela explícitamente; se muestran "
                   "predicciones puntuales de línea base y modelo.")

    avail = data.availability_profile(est)
    if not avail.empty and avail["bicis_promedio"].notna().any():
        st.subheader("Disponibilidad observada (GBFS)")
        fig3 = px.line(avail, x="hour", y="bicis_promedio",
                       labels={"bicis_promedio": "bicis promedio", "hour": "hora"})
        fig3.update_layout(height=320)
        st.plotly_chart(fig3, width="stretch")
    else:
        st.caption("Sin capturas GBFS para esta estación en el periodo (cobertura limitada).")


# --------------------------------------------------------------------------- #
def render_rebalanceo() -> None:
    st.header("Rebalanceo recomendado")
    st.caption("Recomendación es una ESTIMACIÓN del modelo heurístico, no un hecho.")
    moves = data.rebalance_moves()
    if moves.empty:
        st.info("No hay recomendaciones de rebalanceo. Ejecuta `python -m models.rebalance`.")
        return

    total_bikes = int(moves["bikes_to_move"].sum())
    def_before = float(moves["receiver_deficit_before"].fillna(0).sum())
    def_after = float(moves["receiver_deficit_after"].fillna(0).sum())
    c1, c2, c3 = st.columns(3)
    c1.metric("Movimientos", len(moves))
    c2.metric("Bicicletas a mover", total_bikes)
    evitado = 100 * (def_before - def_after) / def_before if def_before else 0
    c3.metric("Desabasto evitado (est.)", f"{evitado:.0f}%")

    md = data.rebalance_map_data()
    if not md.empty and md[["donor_lat", "recv_lat"]].notna().all(axis=1).any():
        md = md.dropna(subset=["donor_lat", "donor_lon", "recv_lat", "recv_lon"])
        line = pdk.Layer(
            "LineLayer", data=md,
            get_source_position="[donor_lon, donor_lat]",
            get_target_position="[recv_lon, recv_lat]",
            get_width="1 + bikes_to_move", get_color="[30, 130, 220]", pickable=True,
        )
        pts = pd.concat([
            md[["donor_lon", "donor_lat"]].rename(columns={"donor_lon": "lon", "donor_lat": "lat"}),
            md[["recv_lon", "recv_lat"]].rename(columns={"recv_lon": "lon", "recv_lat": "lat"}),
        ])
        dots = pdk.Layer("ScatterplotLayer", data=pts, get_position="[lon, lat]",
                         get_fill_color="[40, 40, 40, 160]", get_radius=60)
        view = pdk.ViewState(latitude=float(pts["lat"].mean()), longitude=float(pts["lon"].mean()),
                             zoom=12)
        st.pydeck_chart(pdk.Deck(layers=[line, dots], initial_view_state=view, map_style=None))

    st.subheader("Tabla de movimientos")
    show = moves[[
        "donor_station_id", "receiver_station_id", "bikes_to_move", "distance_m",
        "receiver_deficit_before", "receiver_deficit_after", "confidence",
    ]].rename(columns={
        "donor_station_id": "Donante", "receiver_station_id": "Receptora",
        "bikes_to_move": "Bicis", "distance_m": "Distancia (m)",
        "receiver_deficit_before": "Déficit antes", "receiver_deficit_after": "Déficit después",
        "confidence": "Confianza",
    })
    st.dataframe(show, hide_index=True, width="stretch")
    st.download_button("Descargar recomendaciones (CSV)",
                       moves.to_csv(index=False).encode("utf-8"),
                       file_name="rebalance_recommendations.csv", mime="text/csv")


# --------------------------------------------------------------------------- #
def render_calidad() -> None:
    st.header("Calidad y limitaciones")

    cov = data.gbfs_coverage()
    st.subheader("Cobertura GBFS")
    if cov["capturas"]:
        st.write(f"**{cov['capturas']:,}** capturas de **{cov['estaciones']}** estaciones, "
                 f"del {pd.Timestamp(cov['tmin'])} al {pd.Timestamp(cov['tmax'])}.")
        st.caption("La cobertura GBFS comienza cuando se enciende el colector; no hay "
                   "historia previa a ese momento.")
    else:
        st.info("Sin capturas GBFS. Ejecuta `python -m ingest.collect_gbfs`.")

    st.subheader("Registros descartados por motivo")
    rej = data.rejection_breakdown()
    if not rej.empty:
        fig = px.bar(rej, x="motivo", y="n", labels={"n": "registros"})
        st.plotly_chart(fig, width="stretch")
    else:
        st.write("Sin rechazos registrados.")

    st.subheader("Cobertura del puente de estaciones")
    br = data.bridge_coverage()
    if not br.empty:
        st.dataframe(br, hide_index=True, width="stretch")
    else:
        st.write("Puente de estaciones no construido.")

    st.subheader("Lo que este análisis NO puede decir")
    st.markdown(
        "- Los viajes representan **demanda atendida**: los intentos frustrados cuando "
        "una estación está vacía **no se observan**.\n"
        "- La **cobertura GBFS** empieza cuando se enciende el colector.\n"
        "- Una **predicción no garantiza** disponibilidad futura.\n"
        "- El modelo **no incorpora** tráfico, costo de traslado ni restricciones "
        "operativas completas, salvo que existan datos reales para ello."
    )
