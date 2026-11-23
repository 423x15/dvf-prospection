import streamlit as st
import polars as pl
import folium
from streamlit_folium import st_folium
import requests
import math
from datetime import date


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
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def geocode(address):
    url = "https://api-adresse.data.gouv.fr/search/"
    response = requests.get(url, params={"q": address, "limit": 1}, timeout=10)
    response.raise_for_status()
    data = response.json()
    if not data["features"]:
        return None
    coords = data["features"][0]["geometry"]["coordinates"]
    return coords[1], coords[0]


def _route_dist(rows, start_lat, start_lon):
    coords = [(start_lat, start_lon)] + [(r["latitude"], r["longitude"]) for r in rows]
    return sum(
        haversine(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        for i in range(len(coords) - 1)
    )


def nearest_neighbor(start_lat, start_lon, rows, n):
    """Pick the n geographically nearest stops greedily from start."""
    remaining = list(range(len(rows)))
    route = []
    cur_lat, cur_lon = start_lat, start_lon
    for _ in range(n):
        if not remaining:
            break
        best_i = min(
            remaining,
            key=lambda i, clat=cur_lat, clon=cur_lon: haversine(
                clat, clon, rows[i]["latitude"], rows[i]["longitude"]
            ),
        )
        route.append(rows[best_i])
        cur_lat = rows[best_i]["latitude"]
        cur_lon = rows[best_i]["longitude"]
        remaining.remove(best_i)
    return route


def two_opt(rows, start_lat, start_lon):
    """Iteratively reverse segments to eliminate crossings."""
    best = rows[:]
    best_dist = _route_dist(best, start_lat, start_lon)
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 2, len(best)):
                candidate = best[:i + 1] + best[i + 1:j + 1][::-1] + best[j + 1:]
                d = _route_dist(candidate, start_lat, start_lon)
                if d < best_dist - 1e-9:
                    best, best_dist = candidate, d
                    improved = True
    return best, best_dist


# ============================================================
# SIDEBAR — Map filters
# ============================================================

st.sidebar.header("🎯 Map filters")

map_age_range = st.sidebar.slider(
    "Ownership duration (yrs)",
    min_value=0,
    max_value=30,
    value=(0, 30),
    step=1,
)

map_min_price = st.sidebar.number_input(
    "Min last sale price (€)",
    min_value=0,
    value=0,
    step=10000,
)

map_max_price = st.sidebar.number_input(
    "Max last sale price (€)",
    min_value=0,
    value=2_000_000,
    step=10000,
)

# ============================================================
# SIDEBAR — Route planning
# ============================================================

st.sidebar.divider()
st.sidebar.header("🗺️ Route Planning")

plan_route = st.sidebar.checkbox("Plan an agent route")

if plan_route:
    max_stops = st.sidebar.slider("Max stops", min_value=3, max_value=30, value=10, step=1)

    st.sidebar.markdown("**Route criteria** *(independent from map)*")

    route_age_range = st.sidebar.slider(
        "Ownership duration (yrs)",
        min_value=0,
        max_value=30,
        value=(0, 30),
        step=1,
        key="route_age",
    )

    route_min_price = st.sidebar.number_input(
        "Min price (€)",
        min_value=0,
        value=0,
        step=10000,
        key="route_min_price",
    )

    route_max_price = st.sidebar.number_input(
        "Max price (€)",
        min_value=0,
        value=2_000_000,
        step=10000,
        key="route_max_price",
    )


# ============================================================
# MAIN — Search
# ============================================================

st.title("🏠 DVF Prospection")
st.write(f"{len(df):,} houses with recorded transactions.")

address = st.text_input(
    "📍 Address",
    placeholder="e.g. 10 rue Sainte-Catherine, Bordeaux",
)

radius = st.slider(
    "Search radius",
    min_value=0.5,
    max_value=10.0,
    value=2.0,
    step=0.5,
    format="%.1f km",
)

if not address:
    st.info("Enter an address to get started.")
    st.stop()


# ============================================================
# GEOCODING
# ============================================================

with st.spinner("Geocoding address..."):
    location = geocode(address)

if location is None:
    st.error("Address not found.")
    st.stop()

lat, lon = location


# ============================================================
# BASE DATASET — all properties within radius
# ============================================================

CURRENT_YEAR = date.today().year

delta_lat = radius / 111
delta_lon = radius / (111 * math.cos(math.radians(lat)))

# Bounding-box pre-filter, then exact Haversine, then add ownership_age
all_in_radius = (
    df.filter(
        (pl.col("latitude").is_between(lat - delta_lat, lat + delta_lat))
        & (pl.col("longitude").is_between(lon - delta_lon, lon + delta_lon))
    )
    .with_columns((CURRENT_YEAR - pl.col("last_sale_year")).alias("ownership_age"))
    .with_columns(
        pl.struct(["latitude", "longitude"])
        .map_elements(
            lambda x: haversine(lat, lon, x["latitude"], x["longitude"]),
            return_dtype=pl.Float64,
        )
        .alias("distance_km")
    )
    .filter(pl.col("distance_km") <= radius)
    .sort("distance_km")
)


# ============================================================
# MAP VIEW — apply map filters
# ============================================================

nearby = all_in_radius.filter(
    pl.col("ownership_age").is_between(map_age_range[0], map_age_range[1])
    & (pl.col("last_sale_price").fill_null(0) >= map_min_price)
    & (pl.col("last_sale_price").fill_null(0) <= map_max_price)
)


# ============================================================
# ROUTE COMPUTATION — independent criteria
# ============================================================

route_rows: list[dict] = []
route_total_km = 0.0

if plan_route:
    route_pool = all_in_radius.filter(
        pl.col("ownership_age").is_between(route_age_range[0], route_age_range[1])
        & (pl.col("last_sale_price").fill_null(0) >= route_min_price)
        & (pl.col("last_sale_price").fill_null(0) <= route_max_price)
    )

    if len(route_pool) == 0:
        st.sidebar.warning("No properties match the route criteria.")
    else:
        n = min(max_stops, len(route_pool))
        initial = nearest_neighbor(lat, lon, route_pool.to_dicts(), n)
        route_rows, route_total_km = two_opt(initial, lat, lon)


# ============================================================
# RESULTS header
# ============================================================

col_left, col_right = st.columns([3, 1])
with col_left:
    st.subheader(f"🏠 {len(nearby):,} houses within {radius} km")
with col_right:
    if route_rows:
        st.metric("Route", f"{len(route_rows)} stops", f"{route_total_km:.1f} km total")


# ============================================================
# MAP
# ============================================================

m = folium.Map(location=[lat, lon], zoom_start=14, tiles="OpenStreetMap")

legend_html = """
<div style="
    position: fixed; bottom: 30px; left: 30px; width: 220px;
    background-color: white; border: 2px solid grey; z-index: 9999;
    font-size: 14px; padding: 12px; border-radius: 8px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
">
<b>🏠 Years since last sale</b><br><br>
<span style="color:green;">●</span> 0–2 yrs<br>
<span style="color:blue;">●</span> 2–4 yrs<br>
<span style="color:orange;">●</span> 4–6 yrs<br>
<span style="color:red;">●</span> 6–8 yrs<br>
<span style="color:purple;">●</span> 8–10 yrs<br>
<span style="color:black;">●</span> 10+ yrs
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

folium.Marker(
    [lat, lon],
    popup="Search address",
    icon=folium.Icon(color="black", icon="home"),
).add_to(m)

folium.Circle([lat, lon], radius=radius * 1000, color="blue", fill=False).add_to(m)


# ============================================================
# CIRCLE MARKERS — map view
# ============================================================

route_parcel_ids = {r["l_idpar"] for r in route_rows}

for row in nearby.iter_rows(named=True):
    age = row["ownership_age"]
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

    price = row["last_sale_price"]
    price_str = f"{price:,.0f} €".replace(",", " ") if price else "Unknown"

    popup = (
        f"<b>House</b><br><br>"
        f"Last sale: {row['last_sale_date']}<br>"
        f"Price: {price_str}<br>"
        f"Ownership: {age} yrs<br>"
        f"Distance: {row['distance_km']:.2f} km<br>"
        f"Plot: {row['l_idpar']}"
    )

    folium.CircleMarker(
        [row["latitude"], row["longitude"]],
        radius=5,
        color=color,
        fill=True,
        fill_opacity=0.7,
        popup=folium.Popup(popup, max_width=300),
    ).add_to(m)


# ============================================================
# ROUTE OVERLAY
# ============================================================

if route_rows:
    route_coords = [[lat, lon]] + [[r["latitude"], r["longitude"]] for r in route_rows]

    folium.PolyLine(
        route_coords,
        color="#1a56db",
        weight=3,
        opacity=0.9,
        dash_array="6 4",
    ).add_to(m)

    for i, row in enumerate(route_rows, start=1):
        price = row["last_sale_price"]
        price_str = f"{price:,.0f} €".replace(",", " ") if price else "Unknown"
        popup_html = (
            f"<b>Stop {i}</b><br><br>"
            f"Last sale: {row['last_sale_date']}<br>"
            f"Price: {price_str}<br>"
            f"Ownership: {row['ownership_age']} yrs<br>"
            f"Distance from start: {row['distance_km']:.2f} km"
        )
        folium.Marker(
            [row["latitude"], row["longitude"]],
            icon=folium.DivIcon(
                html=(
                    f'<div style="background:#1a56db;color:white;border-radius:50%;'
                    f'width:24px;height:24px;text-align:center;line-height:24px;'
                    f'font-weight:bold;font-size:12px;border:2px solid white;'
                    f'box-shadow:0 1px 4px rgba(0,0,0,0.5);">{i}</div>'
                ),
                icon_size=(24, 24),
                icon_anchor=(12, 12),
            ),
            popup=folium.Popup(popup_html, max_width=250),
        ).add_to(m)


# ============================================================
# DISPLAY
# ============================================================

st_folium(m, width=None, height=700)


# ============================================================
# ROUTE TABLE
# ============================================================

if route_rows:
    st.subheader(f"🗺️ Optimized route — {len(route_rows)} stops · {route_total_km:.1f} km")
    table = []
    for i, row in enumerate(route_rows, start=1):
        price = row["last_sale_price"]
        table.append({
            "Stop": i,
            "Last sale": str(row["last_sale_date"]),
            "Ownership (yrs)": row["ownership_age"],
            "Price (€)": f"{price:,.0f}".replace(",", " ") if price else "—",
            "Dist. from start (km)": f"{row['distance_km']:.2f}",
            "Plot": row["l_idpar"],
        })
    st.dataframe(pl.DataFrame(table), use_container_width=True, hide_index=True)
