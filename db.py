"""
db.py
SQLite persistence layer for the Dam Sedimentation Monitoring System.
No external database server required -- everything lives in sedapp.db
next to this file, so the whole app runs with `python app.py`.
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "sedapp.db")

REQUIRED_ROLES = ["Surveyor", "GIS Analyst", "Boat Driver"]
MAX_TEAM_SIZE = 7


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dam_name TEXT NOT NULL,
            survey_date TEXT NOT NULL,
            crs_epsg INTEGER NOT NULL DEFAULT 4326,
            fsl_elevation REAL,
            dead_water_elevation REAL,
            current_water_elevation REAL,
            original_design_capacity_m3 REAL,
            status TEXT NOT NULL DEFAULT 'team',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS team_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id INTEGER NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id INTEGER NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,                 -- bathymetry | fsl_boundary | dead_water_point
            source_filename TEXT,
            n_points INTEGER,
            preview_geojson_path TEXT,
            working_xyz_path TEXT,              -- npy of x,y,z in working CRS (meters)
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id INTEGER NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
            method TEXT NOT NULL,
            params_json TEXT,
            dem_path TEXT,
            contours_geojson_path TEXT,
            volume_table_json TEXT,
            siltation_json TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def now():
    return datetime.utcnow().isoformat()


# ---------------- surveys ----------------

def create_survey(dam_name, survey_date, crs_epsg):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO surveys (dam_name, survey_date, crs_epsg, status, created_at) "
        "VALUES (?, ?, ?, 'team', ?)",
        (dam_name, survey_date, crs_epsg, now()),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def get_survey(survey_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM surveys WHERE id=?", (survey_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_surveys():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM surveys ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_survey_levels(survey_id, fsl=None, dwl=None, current=None, design_capacity=None):
    conn = get_conn()
    fields, vals = [], []
    for col, val in [
        ("fsl_elevation", fsl),
        ("dead_water_elevation", dwl),
        ("current_water_elevation", current),
        ("original_design_capacity_m3", design_capacity),
    ]:
        if val is not None:
            fields.append(f"{col}=?")
            vals.append(val)
    if fields:
        vals.append(survey_id)
        conn.execute(f"UPDATE surveys SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    conn.close()


def set_survey_status(survey_id, status):
    conn = get_conn()
    conn.execute("UPDATE surveys SET status=? WHERE id=?", (status, survey_id))
    conn.commit()
    conn.close()


# ---------------- team ----------------

def save_team(survey_id, members):
    """members: list of dicts {name, role} in display order, length 3..7."""
    conn = get_conn()
    conn.execute("DELETE FROM team_members WHERE survey_id=?", (survey_id,))
    for i, m in enumerate(members):
        conn.execute(
            "INSERT INTO team_members (survey_id, seq, name, role) VALUES (?, ?, ?, ?)",
            (survey_id, i, m["name"], m["role"]),
        )
    conn.commit()
    conn.close()


def get_team(survey_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM team_members WHERE survey_id=? ORDER BY seq", (survey_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def validate_team(members):
    """Returns list of error strings; empty list means valid."""
    errors = []
    if not members:
        errors.append("Add at least the three required roles.")
        return errors
    if len(members) > MAX_TEAM_SIZE:
        errors.append(f"Maximum team size is {MAX_TEAM_SIZE} people.")
    roles_present = set()
    for m in members:
        name = (m.get("name") or "").strip()
        role = (m.get("role") or "").strip()
        if not name:
            errors.append("Every team member must have a name.")
        if not role:
            errors.append("Every team member must have a role (no blanks allowed).")
        else:
            roles_present.add(role)
    for req in REQUIRED_ROLES:
        if req not in roles_present:
            errors.append(f"'{req}' is a required role and is missing from the team.")
    return errors


# ---------------- datasets ----------------

def add_dataset(survey_id, kind, source_filename, n_points, preview_geojson_path, working_xyz_path):
    conn = get_conn()
    conn.execute(
        "INSERT INTO datasets (survey_id, kind, source_filename, n_points, "
        "preview_geojson_path, working_xyz_path, created_at) VALUES (?,?,?,?,?,?,?)",
        (survey_id, kind, source_filename, n_points, preview_geojson_path, working_xyz_path, now()),
    )
    conn.commit()
    conn.close()


def get_datasets(survey_id):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM datasets WHERE survey_id=? ORDER BY id", (survey_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_dataset_by_kind(survey_id, kind):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM datasets WHERE survey_id=? AND kind=? ORDER BY id DESC LIMIT 1",
        (survey_id, kind),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------- results ----------------

def save_result(survey_id, method, params, dem_path, contours_path, volume_table, siltation):
    conn = get_conn()
    conn.execute(
        "INSERT INTO results (survey_id, method, params_json, dem_path, contours_geojson_path, "
        "volume_table_json, siltation_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            survey_id,
            method,
            json.dumps(params),
            dem_path,
            contours_path,
            json.dumps(volume_table),
            json.dumps(siltation),
            now(),
        ),
    )
    conn.commit()
    conn.close()


def get_latest_result(survey_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM results WHERE survey_id=? ORDER BY id DESC LIMIT 1", (survey_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["params"] = json.loads(d.pop("params_json") or "{}")
    d["volume_table"] = json.loads(d.pop("volume_table_json") or "[]")
    d["siltation"] = json.loads(d.pop("siltation_json") or "{}")
    return d
