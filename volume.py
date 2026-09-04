"""
volume.py
Elevation - Surface Area - Volume table via the level-pool (surface volume)
method: for each elevation h, Area(h) = raster area of cells at/below h
(i.e. the pool footprint if the reservoir were filled to h), and Volume(h)
is the cumulative trapezoidal integral of Area from the dam bottom to h.

Runs from the lowest surveyed bed elevation up to Full Supply Level (FSL),
marking the Dead Water Level (DWL) and current survey water level as flagged
rows, then computes siltation against a user-supplied design/original
capacity at FSL.
"""
import numpy as np
import rasterio


def elevation_area_volume(dem_path, bottom_elev, fsl_elev, dwl_elev=None, current_elev=None, step=1.0):
    with rasterio.open(dem_path) as src:
        Z = src.read(1)
        Z = np.where(Z == src.nodata, np.nan, Z)
        cell_area = abs(src.transform.a * src.transform.e)  # m^2 per cell

    valid = Z[~np.isnan(Z)]
    if valid.size == 0:
        raise ValueError("Interpolated DEM contains no valid cells; check input data extents.")

    top = fsl_elev
    bottom = bottom_elev
    if top <= bottom:
        raise ValueError("Full Supply Level must be higher than the dam bottom elevation.")

    levels = list(np.arange(bottom, top, step)) + [top]
    levels = sorted(set(round(l, 6) for l in levels))

    rows = []
    areas = []
    for h in levels:
        area = float(np.sum(Z <= h) * cell_area)
        areas.append(area)

    volumes = [0.0]
    for i in range(1, len(levels)):
        dh = levels[i] - levels[i - 1]
        vol_increment = 0.5 * (areas[i] + areas[i - 1]) * dh
        volumes.append(volumes[-1] + vol_increment)

    marks_dwl = _nearest_index(levels, dwl_elev) if dwl_elev is not None else None
    marks_current = _nearest_index(levels, current_elev) if current_elev is not None else None

    for i, h in enumerate(levels):
        rows.append(
            {
                "elevation_m": round(h, 3),
                "surface_area_m2": round(areas[i], 2),
                "surface_area_ha": round(areas[i] / 10000.0, 4),
                "cumulative_volume_m3": round(volumes[i], 2),
                "cumulative_volume_Mm3": round(volumes[i] / 1_000_000.0, 5),
                "is_dead_water_level": (i == marks_dwl),
                "is_current_level": (i == marks_current),
                "is_full_supply_level": (i == len(levels) - 1),
                "is_bottom": (i == 0),
            }
        )
    return rows


def _nearest_index(levels, target):
    arr = np.array(levels)
    return int(np.argmin(np.abs(arr - target)))


def compute_siltation(volume_table, original_design_capacity_m3):
    fsl_row = next((r for r in volume_table if r["is_full_supply_level"]), volume_table[-1])
    current_capacity = fsl_row["cumulative_volume_m3"]

    result = {
        "current_capacity_at_fsl_m3": current_capacity,
        "current_capacity_at_fsl_Mm3": round(current_capacity / 1_000_000.0, 5),
    }
    if original_design_capacity_m3:
        siltation_vol = original_design_capacity_m3 - current_capacity
        result.update(
            {
                "original_design_capacity_m3": original_design_capacity_m3,
                "siltation_volume_m3": round(siltation_vol, 2),
                "siltation_volume_Mm3": round(siltation_vol / 1_000_000.0, 5),
                "siltation_percent": round(100.0 * siltation_vol / original_design_capacity_m3, 3)
                if original_design_capacity_m3 else None,
                "capacity_remaining_percent": round(100.0 * current_capacity / original_design_capacity_m3, 3)
                if original_design_capacity_m3 else None,
            }
        )
    else:
        result.update(
            {
                "original_design_capacity_m3": None,
                "siltation_volume_m3": None,
                "note": "No original/design capacity supplied — showing current surveyed capacity only. "
                        "Enter the original design capacity at FSL to compute siltation loss.",
            }
        )
    return result
