# Dam Sedimentation Monitoring System

A working, self-contained GIS web application for turning bathymetric survey
data into a DEM, classified depth-band map, elevation–area–volume capacity
curve, and siltation figure — no PostGIS/GDAL-server setup required, it runs
as a single Flask process with a local SQLite database.

## What it does

1. **Survey Team** — register up to 7 field team members. `Surveyor`,
   `GIS Analyst`, and `Boat Driver` are mandatory roles; the form will not
   submit if any of them is missing or blank.
2. **Ingest data** — upload:
   - **Bathymetry points** (depth soundings) — CSV, zipped Shapefile,
     KML, or GeoJSON
   - **Full Supply Level (FSL) boundary points** (shoreline surveyed at
     FSL — this closes the basin so the DEM covers bottom-to-rim, not just
     the underwater part) — same formats
   - **Outlet / Dead Water level** marker (optional file; the level value
     itself is entered as a number)
   - Full Supply Level, Dead Water Level, and current survey water level
     (meters), plus an optional original/design capacity at FSL to enable
     the siltation calculation
   All ingested points are shown on a Leaflet map for visual QA before you
   run anything.
3. **Interpolate** — choose **IDW** (power + neighbor count) or
   **Ordinary Kriging** (variogram model), set a grid cell size, and run.
   This builds a raster DEM (GeoTIFF) from bathymetry + FSL points combined.
4. **Classified depth bands** — the DEM is sliced into 1 m elevation bands
   from the surveyed bottom up to the **current water level** and drawn as
   coloured polygons on the map (dark = deep, light = shallow).
5. **Elevation–Area–Volume table** — computed straight from the DEM by the
   level-pool (surface volume) method, in 1 m steps from the bottom up to
   **Full Supply Level**, with the Dead Water Level and Current Level rows
   flagged.
6. **Siltation** — current surveyed capacity at FSL vs. the original/design
   capacity you supply, as both a volume and a percentage.

## Setup

```bash
cd sedapp
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000**.

> `rasterio`/`geopandas`/`fiona` pull in GDAL/PROJ binary wheels from PyPI —
> on Linux/macOS `pip install` alone is normally enough. On Windows, if you
> hit a build error, install via `conda install -c conda-forge geopandas
> rasterio fiona pykrige` instead, then `pip install flask` in the same
> environment.

The app creates `sedapp.db` (SQLite) automatically on first run — no
database server to install or configure. Uploaded files live under `data/`,
generated DEMs/contours under `outputs/`, both keyed by survey ID.

## Coordinate systems — important

Interpolation and volume math need **projected, meters-based** coordinates,
not lon/lat degrees. When you create a survey you set a **working CRS EPSG
code** (default `32735` = WGS84 / UTM Zone 35S, the common choice across
Zimbabwe; use `20935` for Arc 1950 / UTM 35S if that's your survey datum).

- CSV uploads must also specify the **source EPSG** of their x/y columns
  (usually the same as the working CRS).
- Shapefile/KML/GeoJSON uploads carry their own CRS (`.prj` or embedded) and
  are reprojected automatically.
- Z values come from a 3D geometry, or from a column/attribute you name in
  the "Z field" box if auto-detection (`z`, `elevation`, `depth`, …) doesn't
  find one.

## Why FSL boundary points matter

Bathymetry alone only covers the area that was underwater at survey time.
Uploading shoreline points **surveyed at Full Supply Level** gives the
interpolator the rim of the basin too, so the DEM — and therefore the
capacity curve up to FSL — covers the *whole* reservoir, not just today's
wet area. The classified depth-band map, by contrast, is deliberately
capped at the **current** water level, since that's the zone that was
actually surveyed as "underwater" this time out.

## Project layout

```
sedapp/
├── app.py             Flask routes (team → upload → workspace, + JSON API)
├── db.py               SQLite schema & data access
├── geodata_io.py        CSV / zipped-Shapefile / KML / GeoJSON ingestion
├── interpolate.py       IDW + Ordinary Kriging, grid + GeoTIFF writer
├── contours.py           1 m depth-band classification & polygonization
├── volume.py              Elevation-Area-Volume table + siltation calc
├── templates/               team.html, upload.html, workspace.html, ...
├── static/js/map.js, workspace.js    Leaflet map + UI logic
├── static/css/style.css
└── requirements.txt
```

## Extending it

- **Validation**: the interpolation/volume pipeline was tested end-to-end
  against a synthetic bowl-shaped "dam" (bottom 900 m, FSL rim 920 m) and
  against real zipped-Shapefile / GeoJSON / CSV inputs — logic checks out,
  but you should validate against your own Antelope/Masholomosi ZINWA
  datasets and, per your dissertation's validation framework, compare IDW
  vs Kriging RMSE/MAE against ZINWA's manual figures.
- **Multiple surveys over time**: the schema already supports many
  `surveys` rows — add a small "siltation trend" chart comparing
  `cumulative_volume at FSL` across survey dates once you have more than
  one epoch to compare.
- **Auth/deployment**: `app.secret_key` and `debug=True` in `app.py` are
  fine for a dissertation demo on localhost; change both before deploying
  anywhere reachable by others.
