"""Aplicación Streamlit de ECOBICI: dónde faltan bicicletas y a qué hora.

Ejecuta:
    streamlit run app/app.py

Funciona con los datos de muestra (data/sample/) cargados por el pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# `streamlit run app/app.py` coloca la carpeta app/ en sys.path[0] y registra el
# script como el módulo `app`, por lo que `import app` resolvería al script (sin
# __path__) en vez del paquete app/. Forzamos la raíz del repo al frente de
# sys.path y limpiamos ese alias para que los imports `app.*` resuelvan al paquete.
REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if REPO_ROOT in sys.path:
    sys.path.remove(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)
_app_alias = sys.modules.get("app")
if _app_alias is not None and not hasattr(_app_alias, "__path__"):
    del sys.modules["app"]

from app.components import sections  # noqa: E402
from app.utils import data  # noqa: E402
from common.config import get_settings  # noqa: E402

st.set_page_config(page_title="ECOBICI · Demanda y rebalanceo", page_icon="🚲", layout="wide")


@st.cache_resource(show_spinner="Preparando la demostración (solo la primera vez, ~20 s)…")
def _ensure_sample_data() -> str:
    """Si no hay base (p. ej. en Streamlit Community Cloud), construye la muestra.

    Build ATÓMICO: el pipeline se ejecuta contra una base temporal y, solo si
    termina por completo, se mueve a su ubicación final. Así ``has_data()`` únicamente
    es True tras un build completo (si un arranque se interrumpe, el siguiente lo
    rehace). Además **nunca** toca una base existente, protegiendo datos locales
    reales: si el archivo ya existe, no hace nada.
    """
    import os

    from common.config import load_settings

    target = data.db_path()
    if target.exists():
        return "listo"

    tmp = target.with_name("_building_" + target.name)
    for stray in (tmp, tmp.with_name(tmp.name + ".wal")):
        try:
            stray.unlink()
        except FileNotFoundError:
            pass

    prev = os.environ.get("ECOBICI_DUCKDB_PATH")
    os.environ["ECOBICI_DUCKDB_PATH"] = str(tmp)
    load_settings.cache_clear()
    try:
        from run_pipeline import run as run_pipeline

        run_pipeline(sample=True)
    finally:
        if prev is None:
            os.environ.pop("ECOBICI_DUCKDB_PATH", None)
        else:
            os.environ["ECOBICI_DUCKDB_PATH"] = prev
        load_settings.cache_clear()

    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, target)  # swap atómico
    return "construido"


def main() -> None:
    settings = get_settings()
    st.title("🚲 " + settings.get("app", "title", default="ECOBICI"))
    st.caption("Dónde faltan bicicletas y a qué hora — pipeline reproducible de "
               "demanda, disponibilidad y rebalanceo.")

    try:
        _ensure_sample_data()
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudieron preparar los datos de demostración: {exc}")

    if not data.has_data():
        st.warning(
            "No hay datos cargados en la base. Ejecuta el pipeline con datos de muestra:\n\n"
            "```\npython run_pipeline.py\n```\n\n"
            "o consulta el README para cargar datos reales."
        )
        st.stop()

    seccion = st.sidebar.radio(
        "Sección",
        ["Resumen ejecutivo", "Mapa interactivo", "Demanda por estación",
         "Rebalanceo", "Calidad y limitaciones"],
    )
    st.sidebar.markdown("---")
    st.sidebar.caption(f"Base: `{data.db_path().name}`")
    st.sidebar.caption("Datos de muestra sintéticos salvo que hayas cargado el histórico real.")

    if seccion == "Resumen ejecutivo":
        sections.render_resumen()
    elif seccion == "Mapa interactivo":
        sections.render_mapa()
    elif seccion == "Demanda por estación":
        sections.render_demanda()
    elif seccion == "Rebalanceo":
        sections.render_rebalanceo()
    else:
        sections.render_calidad()


if __name__ == "__main__":
    main()
