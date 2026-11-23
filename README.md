# DVF Prospection — find long-held houses around any address

A Streamlit app for real-estate prospecting. Type an address, pick a radius, and see on a map every house around it that has **not changed hands for years** — the owners most likely to be open to selling — together with the price of their last sale.

Built on France's open property-transaction data (**DVF**, *Demandes de valeurs foncières*) and the national address geocoder (**api-adresse.data.gouv.fr**).

## What it does

- Geocodes any French address, then searches a radius from **0.5 to 10 km**.
- Filters houses by **ownership duration** (years since last sale) and by **last sale price**.
- Fast spatial search: bounding-box pre-filter, then exact Haversine distance, on a Polars dataframe.
- Interactive Folium map with a popup per house (last sale year and price).

## Data

`dvf_houses.parquet` (17 MB) is a pre-processed extract: **398,112 houses**, one row per house with its latest sale.

| Column | Meaning |
|---|---|
| `l_idpar` | cadastral parcel id(s) |
| `last_sale_date`, `last_sale_year` | date and year of the latest transaction (2014 → 2025) |
| `last_sale_price` | price of that transaction, in euros |
| `longitude`, `latitude` | WGS84 position (coverage inferred from the data: the Loire / western France area) |
| `x`, `y` | projected coordinates (Lambert-93) |

Source: DVF open data published by the French state on data.gouv.fr. The pre-processing script is not part of this repo yet.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then enter an address such as `10 rue Sainte-Catherine, Bordeaux` (note that the bundled data only covers part of France, so results depend on the area).

## Stack

Python · Streamlit · Polars · Folium · api-adresse.data.gouv.fr

## Author

Alexis Lalanne — [LinkedIn](https://www.linkedin.com/in/alexis-lalanne-183726207)
