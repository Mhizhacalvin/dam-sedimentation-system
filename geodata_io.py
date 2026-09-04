"""
geodata_io.py
Ingests bathymetry / FSL-boundary / dead-water-level data from:
  - CSV  (columns: x/y/z or easting/northing/elevation or lon/lat/elevation)
  - Zipped Shapefile (.zip containing .shp/.shx/.dbf/.prj)
  - KML
  - GeoJSON

Every loader returns:
  xyz_working : (N,3) numpy array in the survey's *working* projected CRS (meters)
  gdf_4326    : a GeoDataFrame reprojected to EPSG:4326, for map preview only

The working CRS is meters-based because area/volume math downstream depends
on it (EPSG:4326 degrees would silently corrupt every m^2/m^3 figure).
"""
import os
import json
import zipfile
import tempfile
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

CSV_XY_ALIASES = {
    "x": ["x", "easting", "east", "lon", "long", "longitude"],
    "y": ["y", "northing", "north", "lat", "latitude"],
    "z": ["z", "elevation", "elev", "depth", "height", "bed_elevation", "value"],
}


def _pick_column(columns, aliases):
    lower = {c.lower(): c for c in columns}
    for alias in aliases:
        if alias in lower:
            return lower[alias]
    return None


def _load_csv(path, z_field=None):
    df = pd.read_csv(path)
    xcol = _pick_column(df.columns, CSV_XY_ALIASES["x"])
    ycol = _pick_column(df.columns, CSV_XY_ALIASES["y"])
    zcol = z_field if (z_field and z_field in df.columns) else _pick_column(df.columns, CSV_XY_ALIASES["z"])
    if not xcol or not ycol:
        raise ValueError(
            "CSV must contain recognizable X/Y columns "
            "(e.g. x,y,z or easting,northing,elevation or lon,lat,elevation)."
        )
    if not zcol:
        raise ValueError(
            "CSV must contain a Z / elevation / depth column "
            "(e.g. z, elevation, depth)."
        )
    df = df[[xcol, ycol, zcol]].dropna()
    df.columns = ["x", "y", "z"]
    return df


def _load_vector(path, driver=None, z_field=None):
    gdf = gpd.read_file(path, driver=driver) if driver else gpd.read_file(path)
    if gdf.empty:
        raise ValueError("No features found in the uploaded file.")
    if gdf.crs is None:
        raise ValueError(
            "The uploaded file has no coordinate reference system (.prj) defined. "
            "Please supply a file with a valid CRS, or use CSV and specify the working EPSG."
        )
    xs, ys, zs = [], [], []
    for geom in gdf.geometry:
        if geom is None:
            continue
        pt = geom if geom.geom_type == "Point" else geom.centroid
        xs.append(pt.x)
        ys.append(pt.y)
        z = pt.z if pt.has_z else None
        zs.append(z)

    if z_field and z_field in gdf.columns:
        zs = gdf[z_field].tolist()

    if any(z is None for z in zs):
        raise ValueError(
            "Could not find a Z value for every point (no 3D geometry and no z-field "
            "attribute selected). Provide 3D points or specify the elevation/depth field."
        )
    df = pd.DataFrame({"x": xs, "y": ys, "z": zs}).dropna()
    return df, gdf


def load_points(path, original_filename, working_epsg, source_epsg=None, z_field=None):
    """
    Returns: (xyz_working ndarray[N,3], gdf_4326 GeoDataFrame for preview, n_points)
    """
    ext = original_filename.lower().rsplit(".", 1)[-1]

    if ext == "csv":
        df = _load_csv(path, z_field=z_field)
        if not source_epsg:
            raise ValueError("CSV upload requires the source EPSG code of the x/y coordinates.")
        gdf = gpd.GeoDataFrame(
            df, geometry=[Point(x, y) for x, y in zip(df.x, df.y)], crs=f"EPSG:{source_epsg}"
        )
    elif ext == "zip":
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if not any(n.lower().endswith(".shp") for n in names):
                raise ValueError("Zip file does not contain a .shp component.")
        vector_path = f"zip://{path}"
        df, gdf = _load_vector(vector_path, z_field=z_field)
        gdf = gpd.GeoDataFrame(df, geometry=gdf.geometry.values[: len(df)], crs=gdf.crs)
    elif ext == "kml":
        try:
            import fiona
            fiona.drvsupport.supported_drivers["KML"] = "rw"
            fiona.drvsupport.supported_drivers["LIBKML"] = "rw"
        except Exception:
            pass
        df, gdf = _load_vector(path, driver="KML", z_field=z_field)
        gdf = gpd.GeoDataFrame(df, geometry=gdf.geometry.values[: len(df)], crs=gdf.crs or "EPSG:4326")
    elif ext in ("geojson", "json"):
        df, gdf = _load_vector(path, z_field=z_field)
        gdf = gpd.GeoDataFrame(df, geometry=gdf.geometry.values[: len(df)], crs=gdf.crs or "EPSG:4326")
    else:
        raise ValueError(f"Unsupported file type: .{ext}. Use CSV, zipped Shapefile, KML, or GeoJSON.")

    # working CRS (projected, meters) for interpolation/volume math
    gdf_working = gdf.to_crs(epsg=working_epsg)
    xyz_working = np.column_stack(
        [gdf_working.geometry.x.values, gdf_working.geometry.y.values, df["z"].values.astype(float)]
    )

    # 4326 copy for Leaflet preview
    gdf_4326 = gdf.to_crs(epsg=4326)
    gdf_4326["z"] = df["z"].values

    return xyz_working, gdf_4326, len(df)


def save_preview_geojson(gdf_4326, out_path):
    gdf_4326[["z", "geometry"]].to_file(out_path, driver="GeoJSON")
    return out_path
