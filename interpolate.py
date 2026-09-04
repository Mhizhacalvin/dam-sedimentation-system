"""
interpolate.py
Builds a regular grid over the combined bathymetry + FSL-boundary point cloud,
interpolates a DEM using IDW or Ordinary Kriging, and writes it as a GeoTIFF.
"""
import numpy as np
import rasterio
from rasterio.transform import from_origin
from scipy.spatial import cKDTree


def build_grid(xyz, cell_size, buffer_cells=1):
    xmin, ymin = xyz[:, 0].min(), xyz[:, 1].min()
    xmax, ymax = xyz[:, 0].max(), xyz[:, 1].max()
    xmin -= buffer_cells * cell_size
    ymin -= buffer_cells * cell_size
    xmax += buffer_cells * cell_size
    ymax += buffer_cells * cell_size

    ncols = max(2, int(np.ceil((xmax - xmin) / cell_size)))
    nrows = max(2, int(np.ceil((ymax - ymin) / cell_size)))

    # cap grid size so a fat-fingered small cell size on a big extent
    # doesn't try to allocate a multi-GB array
    MAX_CELLS = 4_000_000
    if ncols * nrows > MAX_CELLS:
        scale = ((ncols * nrows) / MAX_CELLS) ** 0.5
        cell_size *= scale
        ncols = max(2, int(np.ceil((xmax - xmin) / cell_size)))
        nrows = max(2, int(np.ceil((ymax - ymin) / cell_size)))

    xs = xmin + (np.arange(ncols) + 0.5) * cell_size
    ys = ymax - (np.arange(nrows) + 0.5) * cell_size  # top-down, north-up raster
    grid_x, grid_y = np.meshgrid(xs, ys)
    transform = from_origin(xmin, ymax, cell_size, cell_size)
    return grid_x, grid_y, transform, nrows, ncols, cell_size


def idw(xyz, grid_x, grid_y, power=2.0, k=12, smoothing=1e-6):
    tree = cKDTree(xyz[:, :2])
    pts = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    k_eff = min(k, len(xyz))
    dist, idx = tree.query(pts, k=k_eff)
    if k_eff == 1:
        dist = dist[:, None]
        idx = idx[:, None]
    dist = np.maximum(dist, smoothing)
    weights = 1.0 / (dist ** power)
    weights /= weights.sum(axis=1, keepdims=True)
    z = xyz[:, 2][idx]
    zi = np.sum(weights * z, axis=1)
    # exact match at coincident points
    zero_mask = dist[:, 0] <= smoothing
    zi[zero_mask] = z[zero_mask, 0]
    return zi.reshape(grid_x.shape)


def ordinary_kriging(xyz, grid_x, grid_y, variogram_model="linear", max_points=1500):
    from pykrige.ok import OrdinaryKriging

    pts = xyz
    if len(pts) > max_points:
        # subsample for tractable kriging on dense bathymetry surveys;
        # random, seeded for reproducibility
        rng = np.random.default_rng(42)
        sel = rng.choice(len(pts), size=max_points, replace=False)
        pts = pts[sel]

    ok = OrdinaryKriging(
        pts[:, 0], pts[:, 1], pts[:, 2],
        variogram_model=variogram_model,
        verbose=False,
        enable_plotting=False,
    )
    xs = grid_x[0, :]
    ys = grid_y[:, 0]
    z, ss = ok.execute("grid", xs, ys)
    return np.asarray(z)


def run_interpolation(xyz, cell_size, method="idw", params=None, crs_epsg=4326):
    params = params or {}
    grid_x, grid_y, transform, nrows, ncols, cell_size = build_grid(xyz, cell_size)

    if method == "idw":
        Z = idw(xyz, grid_x, grid_y, power=params.get("power", 2.0), k=params.get("k", 12))
    elif method == "kriging":
        Z = ordinary_kriging(xyz, grid_x, grid_y, variogram_model=params.get("variogram_model", "linear"))
    else:
        raise ValueError(f"Unknown interpolation method: {method}")

    return Z, transform, cell_size, nrows, ncols


def write_geotiff(path, Z, transform, crs_epsg):
    with rasterio.open(
        path, "w",
        driver="GTiff",
        height=Z.shape[0], width=Z.shape[1],
        count=1, dtype="float32",
        crs=f"EPSG:{crs_epsg}",
        transform=transform,
        nodata=np.nan,
    ) as dst:
        dst.write(Z.astype("float32"), 1)
    return path
