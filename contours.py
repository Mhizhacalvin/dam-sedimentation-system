"""
contours.py
Classifies the interpolated DEM into 1 m elevation bands from the dam
bottom up to the CURRENT water level (the zone actually inundated at
survey time), and polygonizes each band into GeoJSON for map display.
"""
import numpy as np
import rasterio
from rasterio.features import shapes as rio_shapes
import geopandas as gpd
from shapely.geometry import shape


def classify_bands(Z, bottom_elev, top_elev, interval=1.0):
    """
    Returns an int16 class array where class i covers
    [bottom + i*interval, bottom + (i+1)*interval), plus -1 for nodata/out-of-range.
    """
    classes = np.full(Z.shape, -1, dtype=np.int16)
    valid = ~np.isnan(Z)
    in_range = valid & (Z >= bottom_elev) & (Z <= top_elev + 1e-6)
    band = np.floor((Z - bottom_elev) / interval).astype(np.int16)
    n_bands = int(np.ceil((top_elev - bottom_elev) / interval))
    band = np.clip(band, 0, max(n_bands - 1, 0))
    classes[in_range] = band[in_range]
    return classes, n_bands


def polygonize_classes(classes, transform, crs_epsg, bottom_elev, interval=1.0):
    mask = classes >= 0
    records = []
    for geom, val in rio_shapes(classes, mask=mask, transform=transform):
        band = int(val)
        records.append(
            {
                "band": band,
                "depth_min": round(bottom_elev + band * interval, 3),
                "depth_max": round(bottom_elev + (band + 1) * interval, 3),
                "geometry": shape(geom),
            }
        )
    if not records:
        return gpd.GeoDataFrame(columns=["band", "depth_min", "depth_max", "geometry"], crs=f"EPSG:{crs_epsg}")
    gdf = gpd.GeoDataFrame(records, crs=f"EPSG:{crs_epsg}")
    # dissolve slivers of the same band that polygonize split apart
    gdf = gdf.dissolve(by="band", as_index=False)
    return gdf


def build_contour_polygons(dem_path, bottom_elev, top_elev, working_epsg, interval=1.0):
    with rasterio.open(dem_path) as src:
        Z = src.read(1)
        Z = np.where(Z == src.nodata, np.nan, Z)
        transform = src.transform

    classes, n_bands = classify_bands(Z, bottom_elev, top_elev, interval)
    gdf = polygonize_classes(classes, transform, working_epsg, bottom_elev, interval)
    gdf_4326 = gdf.to_crs(epsg=4326) if len(gdf) else gdf
    return gdf_4326, n_bands
