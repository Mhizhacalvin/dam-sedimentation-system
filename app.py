import os
import json
import traceback
from datetime import date

from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file, flash

import db
import geodata_io
import interpolate
import contours
import volume as vol_mod

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = "dam-sedimentation-monitoring-dev-key"  # change for any real deployment
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB uploads

REQUIRED_ROLES = db.REQUIRED_ROLES
MAX_TEAM_SIZE = db.MAX_TEAM_SIZE


def survey_dir(survey_id, sub):
    d = os.path.join(sub, str(survey_id))
    os.makedirs(d, exist_ok=True)
    return d


# ----------------------------------------------------------------- pages --

@app.route("/")
def index():
    surveys = db.list_surveys()
    return render_template("index.html", surveys=surveys)


@app.route("/team", methods=["GET", "POST"])
def team():
    if request.method == "GET":
        return render_template(
            "team.html", required_roles=REQUIRED_ROLES, max_team=MAX_TEAM_SIZE,
            dam_name="", survey_date=date.today().isoformat(), crs_epsg=32735, errors=[],
            members=[{"name": "", "role": r} for r in REQUIRED_ROLES],
        )

    dam_name = request.form.get("dam_name", "").strip()
    survey_date = request.form.get("survey_date", "").strip()
    crs_epsg = request.form.get("crs_epsg", "32735").strip()

    names = request.form.getlist("member_name")
    roles = request.form.getlist("member_role")
    members = [{"name": n.strip(), "role": r.strip()} for n, r in zip(names, roles) if n.strip() or r.strip()]

    errors = []
    if not dam_name:
        errors.append("Dam / reservoir name is required.")
    if not survey_date:
        errors.append("Survey date is required.")
    try:
        crs_epsg_int = int(crs_epsg)
    except ValueError:
        errors.append("Working CRS EPSG code must be numeric (e.g. 32735 for UTM 35S).")
        crs_epsg_int = None

    errors.extend(db.validate_team(members))

    if errors:
        return render_template(
            "team.html", required_roles=REQUIRED_ROLES, max_team=MAX_TEAM_SIZE,
            dam_name=dam_name, survey_date=survey_date, crs_epsg=crs_epsg or 32735,
            errors=errors, members=members or [{"name": "", "role": r} for r in REQUIRED_ROLES],
        )

    survey_id = db.create_survey(dam_name, survey_date, crs_epsg_int)
    db.save_team(survey_id, members)
    db.set_survey_status(survey_id, "upload")
    return redirect(url_for("upload", survey_id=survey_id))


@app.route("/upload/<int:survey_id>", methods=["GET", "POST"])
def upload(survey_id):
    survey = db.get_survey(survey_id)
    if not survey:
        return "Survey not found", 404

    if request.method == "GET":
        datasets = db.get_datasets(survey_id)
        return render_template("upload.html", survey=survey, datasets=datasets, errors=[])

    errors = []
    try:
        fsl = float(request.form.get("fsl_elevation"))
        dwl = float(request.form.get("dead_water_elevation"))
        current = float(request.form.get("current_water_elevation"))
    except (TypeError, ValueError):
        errors.append("Full Supply Level, Dead Water Level and Current Water Level must all be numbers (meters).")
        fsl = dwl = current = None

    design_capacity_raw = request.form.get("original_design_capacity_m3", "").strip()
    design_capacity = float(design_capacity_raw) if design_capacity_raw else None

    if fsl is not None and dwl is not None and current is not None:
        if not (dwl < current <= fsl):
            errors.append("Levels must satisfy: Dead Water Level < Current Water Level <= Full Supply Level.")

    upload_specs = [
        ("bathymetry_file", "bathymetry", True),
        ("fsl_file", "fsl_boundary", True),
        ("dwl_file", "dead_water_point", False),
    ]
    saved_any = {}
    d = survey_dir(survey_id, UPLOAD_DIR)

    for field, kind, required in upload_specs:
        f = request.files.get(field)
        if not f or not f.filename:
            if required and not db.get_dataset_by_kind(survey_id, kind):
                errors.append(f"'{field.replace('_', ' ')}' file is required.")
            continue
        z_field = request.form.get(f"{field}_zfield", "").strip() or None
        source_epsg = request.form.get(f"{field}_source_epsg", "").strip() or None
        fname = f.filename
        fpath = os.path.join(d, f"{kind}_{fname}")
        f.save(fpath)
        try:
            xyz, gdf_4326, n = geodata_io.load_points(
                fpath, fname, working_epsg=survey["crs_epsg"], source_epsg=source_epsg, z_field=z_field
            )
        except Exception as e:
            errors.append(f"Could not read {field.replace('_', ' ')}: {e}")
            continue

        xyz_path = os.path.join(d, f"{kind}.npy")
        import numpy as np
        np.save(xyz_path, xyz)
        geojson_path = os.path.join(d, f"{kind}_preview.geojson")
        geodata_io.save_preview_geojson(gdf_4326, geojson_path)

        db.add_dataset(survey_id, kind, fname, n, geojson_path, xyz_path)
        saved_any[kind] = n

    if errors:
        datasets = db.get_datasets(survey_id)
        return render_template("upload.html", survey=survey, datasets=datasets, errors=errors)

    db.update_survey_levels(survey_id, fsl=fsl, dwl=dwl, current=current, design_capacity=design_capacity)
    db.set_survey_status(survey_id, "workspace")
    return redirect(url_for("workspace", survey_id=survey_id))


@app.route("/workspace/<int:survey_id>")
def workspace(survey_id):
    survey = db.get_survey(survey_id)
    if not survey:
        return "Survey not found", 404
    datasets = db.get_datasets(survey_id)
    team_members = db.get_team(survey_id)
    latest = db.get_latest_result(survey_id)
    return render_template("workspace.html", survey=survey, datasets=datasets, team=team_members, latest=latest)


# ------------------------------------------------------------------ API --

@app.route("/api/survey/<int:survey_id>/preview")
def api_preview(survey_id):
    datasets = db.get_datasets(survey_id)
    out = {}
    for ds in datasets:
        if ds["preview_geojson_path"] and os.path.exists(ds["preview_geojson_path"]):
            with open(ds["preview_geojson_path"]) as f:
                out[ds["kind"]] = json.load(f)
    return jsonify(out)


@app.route("/api/survey/<int:survey_id>/interpolate", methods=["POST"])
def api_interpolate(survey_id):
    survey = db.get_survey(survey_id)
    if not survey:
        return jsonify({"error": "Survey not found"}), 404

    payload = request.get_json(force=True)
    method = payload.get("method", "idw")
    cell_size = float(payload.get("cell_size", 5.0))
    params = payload.get("params", {})

    try:
        import numpy as np
        bathy_ds = db.get_dataset_by_kind(survey_id, "bathymetry")
        fsl_ds = db.get_dataset_by_kind(survey_id, "fsl_boundary")
        if not bathy_ds or not fsl_ds:
            return jsonify({"error": "Bathymetry and FSL boundary datasets are both required before interpolating."}), 400

        bathy_xyz = np.load(bathy_ds["working_xyz_path"])
        fsl_xyz = np.load(fsl_ds["working_xyz_path"])
        xyz = np.vstack([bathy_xyz, fsl_xyz])

        Z, transform, cell_size_used, nrows, ncols = interpolate.run_interpolation(
            xyz, cell_size=cell_size, method=method, params=params, crs_epsg=survey["crs_epsg"]
        )

        out_dir = survey_dir(survey_id, OUTPUT_DIR)
        dem_path = os.path.join(out_dir, "dem.tif")
        interpolate.write_geotiff(dem_path, Z, transform, survey["crs_epsg"])

        bottom_elev = float(np.nanmin(Z))
        top_for_contours = survey["current_water_elevation"]
        gdf_contours, n_bands = contours.build_contour_polygons(
            dem_path, bottom_elev=bottom_elev, top_elev=top_for_contours,
            working_epsg=survey["crs_epsg"], interval=1.0,
        )
        contours_path = os.path.join(out_dir, "contours.geojson")
        if len(gdf_contours):
            gdf_contours.to_file(contours_path, driver="GeoJSON")
            with open(contours_path) as f:
                contours_geojson = json.load(f)
        else:
            contours_geojson = {"type": "FeatureCollection", "features": []}
            with open(contours_path, "w") as f:
                json.dump(contours_geojson, f)

        vtable = vol_mod.elevation_area_volume(
            dem_path,
            bottom_elev=bottom_elev,
            fsl_elev=survey["fsl_elevation"],
            dwl_elev=survey["dead_water_elevation"],
            current_elev=survey["current_water_elevation"],
            step=1.0,
        )
        siltation = vol_mod.compute_siltation(vtable, survey["original_design_capacity_m3"])

        db.save_result(
            survey_id, method, {"cell_size": cell_size_used, **params},
            dem_path, contours_path, vtable, siltation,
        )
        db.set_survey_status(survey_id, "complete")

        return jsonify({
            "ok": True,
            "method": method,
            "cell_size": cell_size_used,
            "grid_shape": [nrows, ncols],
            "bottom_elevation_m": round(bottom_elev, 3),
            "n_contour_bands": n_bands,
            "contours_geojson": contours_geojson,
            "volume_table": vtable,
            "siltation": siltation,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/survey/<int:survey_id>/results")
def api_results(survey_id):
    latest = db.get_latest_result(survey_id)
    if not latest:
        return jsonify({"error": "No results yet"}), 404
    contours_geojson = {"type": "FeatureCollection", "features": []}
    if latest["contours_geojson_path"] and os.path.exists(latest["contours_geojson_path"]):
        with open(latest["contours_geojson_path"]) as f:
            contours_geojson = json.load(f)
    latest["contours_geojson"] = contours_geojson
    return jsonify(latest)


@app.route("/survey/<int:survey_id>/dem.tif")
def download_dem(survey_id):
    latest = db.get_latest_result(survey_id)
    if not latest or not latest.get("dem_path") or not os.path.exists(latest["dem_path"]):
        return "No DEM available", 404
    return send_file(latest["dem_path"], as_attachment=True, download_name=f"survey_{survey_id}_dem.tif")


@app.route("/survey/<int:survey_id>/volume_table.csv")
def download_volume_csv(survey_id):
    import csv
    import io
    latest = db.get_latest_result(survey_id)
    if not latest:
        return "No results available", 404
    buf = io.StringIO()
    fieldnames = list(latest["volume_table"][0].keys()) if latest["volume_table"] else []
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in latest["volume_table"]:
        writer.writerow(row)
    buf.seek(0)
    mem = io.BytesIO(buf.getvalue().encode("utf-8"))
    return send_file(mem, as_attachment=True, download_name=f"survey_{survey_id}_volume_table.csv", mimetype="text/csv")


if __name__ == "__main__":
    db.init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
