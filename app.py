import streamlit as st
import polars as pl
import folium
from streamlit_folium import st_folium
import requests
import math


# ============================================================
# CONFIG
# ============================================================

st.set_page_config(
    page_title="DVF Prospection",
    page_icon="🏠",
    layout="wide",
)

DATA_PATH = "dvf_houses.parquet"


# ============================================================
# DATA
# ============================================================

@st.cache_data
def load_data():

    return pl.read_parquet(DATA_PATH)


df = load_data()


# ============================================================
# FUNCTIONS
# ============================================================

def haversine(lat1, lon1, lat2, lon2):

    R = 6371

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        +
        math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    return (
        2
        * R
        * math.asin(math.sqrt(a))
    )


def geocode(address):

    url = "https://api-adresse.data.gouv.fr/search/"

    response = requests.get(
        url,
        params={
            "q": address,
            "limit": 1,
        },
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()

    if not data["features"]:
        return None

    coordinates = (
        data["features"][0]
        ["geometry"]
        ["coordinates"]
    )

    return coordinates[1], coordinates[0]


# ============================================================
# UI
# ============================================================

st.title("🏠 DVF Prospection")

st.write(
    f"{len(df):,} maisons avec historique de transaction."
)


# ============================================================
# SEARCH
# ============================================================

address = st.text_input(
    "📍 Adresse à explorer",
    placeholder="Ex : 10 rue Sainte-Catherine, Bordeaux",
)


radius = st.slider(
    "Rayon de recherche",
    min_value=0.5,
    max_value=10.0,
    value=2.0,
    step=0.5,
    format="%.1f km",
)

st.sidebar.header("🎯 Filtres")

# Ancienneté minimale depuis la dernière vente
min_age = st.sidebar.slider(
    "Ancienneté minimale de détention",
    min_value=0,
    max_value=20,
    value=0,
    step=1,
    format="%d ans",
)

# Ancienneté maximale
max_age = st.sidebar.slider(
    "Ancienneté maximale de détention",
    min_value=1,
    max_value=30,
    value=30,
    step=1,
    format="%d ans",
)

# Prix minimum
min_price = st.sidebar.number_input(
    "Prix minimum de la dernière vente (€)",
    min_value=0,
    value=0,
    step=10000,
)

# Prix maximum
max_price = st.sidebar.number_input(
    "Prix maximum de la dernière vente (€)",
    min_value=0,
    value=2_000_000,
    step=10000,
)

if not address:

    st.info(
        "Entrez une adresse pour commencer."
    )

    st.stop()


# ============================================================
# GEOCODING
# ============================================================

with st.spinner("Recherche de l'adresse..."):

    location = geocode(address)


if location is None:

    st.error(
        "Adresse introuvable."
    )

    st.stop()


lat, lon = location


# ============================================================
# FILTER SPATIAL
# ============================================================

# Première optimisation :
# bounding box avant Haversine.

delta_lat = radius / 111

delta_lon = radius / (
    111 * math.cos(
        math.radians(lat)
    )
)


nearby = df.filter(
    (pl.col("latitude") >= lat - delta_lat)
    &
    (pl.col("latitude") <= lat + delta_lat)
    &
    (pl.col("longitude") >= lon - delta_lon)
    &
    (pl.col("longitude") <= lon + delta_lon)
)

CURRENT_YEAR = 2026

nearby = nearby.with_columns(
    (
        CURRENT_YEAR - pl.col("last_sale_year")
    ).alias("ownership_age")
)

nearby = nearby.filter(
    (pl.col("ownership_age") >= min_age)
    &
    (pl.col("ownership_age") <= max_age)
    &
    (
        pl.col("last_sale_price").fill_null(0)
        >= min_price
    )
    &
    (
        pl.col("last_sale_price").fill_null(0)
        <= max_price
    )
)

# ============================================================
# DISTANCE EXACTE
# ============================================================

nearby = nearby.with_columns(
    pl.struct(
        ["latitude", "longitude"]
    )
    .map_elements(
        lambda x: haversine(
            lat,
            lon,
            x["latitude"],
            x["longitude"],
        ),
        return_dtype=pl.Float64,
    )
    .alias("distance_km")
)


nearby = nearby.filter(
    pl.col("distance_km") <= radius
)


# ============================================================
# SORT
# ============================================================

nearby = nearby.sort(
    "distance_km"
)


# ============================================================
# RESULTS
# ============================================================

st.subheader(
    f"🏠 {len(nearby):,} maisons dans un rayon de {radius} km"
)


# ============================================================
# MAP
# ============================================================

m = folium.Map(
    location=[lat, lon],
    zoom_start=14,
    tiles="OpenStreetMap",
)

legend_html = """
<div style="
    position: fixed;
    bottom: 30px;
    left: 30px;
    width: 220px;
    background-color: white;
    border: 2px solid grey;
    z-index: 9999;
    font-size: 14px;
    padding: 12px;
    border-radius: 8px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
">

<b>🏠 Ancienneté depuis la vente</b><br><br>

<span style="color:green;">●</span>
0–2 ans<br>

<span style="color:blue;">●</span>
2–4 ans<br>

<span style="color:orange;">●</span>
4–6 ans<br>

<span style="color:red;">●</span>
6–8 ans<br>

<span style="color:purple;">●</span>
8–10 ans<br>

<span style="color:black;">●</span>
+10 ans

</div>
"""

m.get_root().html.add_child(
    folium.Element(legend_html)
)
# Point de recherche

folium.Marker(
    [lat, lon],
    popup="Adresse recherchée",
    icon=folium.Icon(
        color="black",
        icon="home",
    ),
).add_to(m)


# Cercle

folium.Circle(
    [lat, lon],
    radius=radius * 1000,
    color="blue",
    fill=False,
).add_to(m)


# ============================================================
# MARKERS
# ============================================================

CURRENT_YEAR = 2026

for row in nearby.iter_rows(named=True):

    age = (
        CURRENT_YEAR
        - row["last_sale_year"]
    )


    # --------------------------------------------------------
    # COULEUR
    # --------------------------------------------------------

    if age <= 2:

        color = "green"

    elif age <= 4:

        color = "blue"

    elif age <= 6:

        color = "orange"

    elif age <= 8:

        color = "red"

    elif age <= 10:

        color = "purple"

    else:

        color = "black"


    # --------------------------------------------------------
    # POPUP
    # --------------------------------------------------------

    price = row["last_sale_price"]

    if price:

        price = f"{price:,.0f} €".replace(",", " ")

    else:

        price = "Inconnu"


    popup = f"""
    <b>Maison</b><br><br>

    Dernière vente :
    {row["last_sale_date"]}<br>

    Prix :
    {price}<br>

    Ancienneté :
    {age} ans<br>

    Distance :
    {row["distance_km"]:.2f} km<br>

    Parcelle :
    {row["l_idpar"]}
    """


    folium.CircleMarker(
        [
            row["latitude"],
            row["longitude"],
        ],
        radius=5,
        color=color,
        fill=True,
        fill_opacity=0.7,
        popup=folium.Popup(
            popup,
            max_width=300,
        ),
    ).add_to(m)


# ============================================================
# DISPLAY
# ============================================================

st_folium(
    m,
    width=None,
    height=700,
)