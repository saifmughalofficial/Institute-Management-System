"""Per-institution backup and restore (database rows + uploaded files in one ZIP).

A backup holds only one institution's rows. Before anything is restored, every
row is checked: its institution_id must match the backup, and every reference
column must point at a row inside the same backup. A tampered file therefore
cannot attach data to (or read through) another institution.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import PurePosixPath

from . import db
from .accounts import ValidationError

FORMAT = "ims-tenant-backup"
VERSION = 1

# Parents before children so foreign keys are satisfied while inserting.
TABLE_ORDER = [
    "academic_years", "terms", "faculties", "departments", "programs", "staff", "classes",
    "subjects", "teacher_assignments", "guardians", "students", "student_guardians", "users",
    "user_permissions", "applications", "documents", "student_history", "change_requests",
    "enrollments", "attendance", "attendance_corrections", "staff_attendance", "leave_requests",
    "timetable", "calendar_events", "fee_types", "fee_structures", "invoices", "invoice_items",
    "payments", "student_credits", "discount_requests", "scholarships", "exams", "marksheets",
    "results", "result_corrections", "notices", "notice_reads", "homework", "homework_submissions",
    "books", "book_copies", "book_issues", "transport_routes", "transport_vehicles",
    "transport_assignments", "hostel_rooms", "hostel_allocations", "assets", "maintenance_requests",
    "asset_movements", "audit_log", "counters",
]
assert set(TABLE_ORDER) == db.TENANT_TABLES


def _columns(table: str) -> list[str]:
    return [r["name"] for r in db.query(f"PRAGMA table_info({table})")]


def create_backup(iid: int) -> bytes:
    inst = db.query_one("SELECT * FROM institutions WHERE id=?", (iid,))
    data = {"institution": inst, "tables": {}}
    for t in TABLE_ORDER:
        data["tables"][t] = db.query(f"SELECT * FROM {t} WHERE institution_id=?", (iid,))
    payload = json.dumps(data, default=str).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.json", payload)
        root = db.media_root() / "institutions" / str(iid)
        files = []
        if root.exists():
            for f in root.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(db.media_root()).as_posix()
                    z.write(f, "media/" + rel)
                    files.append(rel)
        z.writestr("manifest.json", json.dumps({
            "format": FORMAT, "version": VERSION, "institution_id": iid,
            "institution_name": inst["name"], "created_at": db.now(),
            "sha256": hashlib.sha256(payload).hexdigest(), "files": files,
            "counts": {t: len(r) for t, r in data["tables"].items()}}))
    return buf.getvalue()


def read_backup(raw: bytes) -> tuple[dict, dict, zipfile.ZipFile]:
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        manifest = json.loads(z.read("manifest.json"))
        payload = z.read("data.json")
    except Exception as exc:
        raise ValidationError("This is not a valid institution backup file.") from exc
    if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
        raise ValidationError("Unsupported backup format.")
    if hashlib.sha256(payload).hexdigest() != manifest.get("sha256"):
        raise ValidationError("Backup checksum mismatch: the file is damaged or was modified.")
    return manifest, json.loads(payload), z


def validate(manifest: dict, data: dict):
    iid = int(manifest["institution_id"])
    inst = data.get("institution") or {}
    if int(inst.get("id", -1)) != iid:
        raise ValidationError("Backup institution does not match its manifest.")
    tables = data.get("tables", {})
    unknown = set(tables) - db.TENANT_TABLES
    if unknown:
        raise ValidationError(f"Unknown tables in backup: {', '.join(sorted(unknown))}")
    ids = {t: {int(r["id"]) for r in rows if "id" in r} for t, rows in tables.items()}
    for t, rows in tables.items():
        cols = set(_columns(t))
        for r in rows:
            if set(r) - cols:
                raise ValidationError(f"Unexpected columns in {t}.")
            if int(r.get("institution_id", -1)) != iid:
                raise ValidationError(f"A row in {t} belongs to another institution.")
            for col, val in r.items():
                ref = db.FK_MAP.get(col)
                if ref and val not in (None, "") and int(val) not in ids.get(ref, set()):
                    raise ValidationError(f"{t}.{col}={val} points outside this backup.")
        for path_col in ("file_path", "logo_path", "photo_path"):
            for r in rows:
                if r.get(path_col):
                    _check_media_path(r[path_col], iid)
    if inst.get("logo_path"):
        _check_media_path(inst["logo_path"], iid)
    for f in manifest.get("files", []):
        _check_media_path(f, iid)


def _check_media_path(path: str, iid: int):
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or p.parts[:2] != ("institutions", str(iid)):
        raise ValidationError("Backup contains a file path outside this institution's folder.")


def restore(raw: bytes, *, expected_iid: int | None = None) -> int:
    """Restore a backup.

    expected_iid given: replace that institution's data (must match the backup).
    expected_iid None: restore onto a server where the institution doesn't
    exist yet (e.g. after a fresh Streamlit Cloud start).
    """
    manifest, data, z = read_backup(raw)
    validate(manifest, data)
    iid = int(manifest["institution_id"])
    existing = db.query_one("SELECT id FROM institutions WHERE id=?", (iid,))
    if expected_iid is not None and expected_iid != iid:
        raise ValidationError("This backup belongs to a different institution.")
    if expected_iid is None and existing:
        raise ValidationError("This institution already exists here. Sign in and restore from "
                              "Backup & restore instead.")
    users = data["tables"].get("users", [])
    for u in users:
        clash = db.query_one("SELECT id FROM users WHERE institution_id<>? AND (username=? OR "
                             "(email<>'' AND email=?))", (iid, u["username"], u.get("email") or ""))
        if clash:
            raise ValidationError(f"Username/email '{u['username']}' is used by another institution.")
    other_ids = {}
    for t, rows in data["tables"].items():
        if rows and "id" in rows[0]:
            found = db.query(f"SELECT id FROM {t} WHERE institution_id<>? AND id IN "
                             f"({','.join(str(int(r['id'])) for r in rows)})", (iid,))
            if found:
                other_ids[t] = len(found)
    if other_ids:
        raise ValidationError("Record ids in this backup are already used by another institution "
                              "on this server; it cannot be restored here.")

    inst = data["institution"]
    with db.transaction() as con:
        con.execute("PRAGMA defer_foreign_keys=ON")
        for t in reversed(TABLE_ORDER):
            con.execute(f"DELETE FROM {t} WHERE institution_id=?", (iid,))
        cols = [c for c in _columns("institutions") if c in inst]
        if existing:
            con.execute(f"UPDATE institutions SET {', '.join(f'{c}=?' for c in cols if c != 'id')} WHERE id=?",
                        (*[inst[c] for c in cols if c != "id"], iid))
        else:
            con.execute(f"INSERT INTO institutions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        tuple(inst[c] for c in cols))
        for t in TABLE_ORDER:
            for r in data["tables"].get(t, []):
                keys = list(r)
                con.execute(f"INSERT INTO {t} ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                            tuple(r[k] for k in keys))
    # Files: replace this institution's folder with the backup's copy.
    root = db.media_root() / "institutions" / str(iid)
    for name in z.namelist():
        if name.startswith("media/"):
            rel = name[len("media/"):]
            _check_media_path(rel, iid)
            target = db.media_root() / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
    db.execute("INSERT INTO audit_log(institution_id, user_id, action, object_type, object_id, details, created_at)"
               " VALUES (?,?,?,?,?,?,?)", (iid, None, "backup_restored", "institution", iid,
                                            json.dumps({"backup_created": manifest.get("created_at")}), db.now()))
    root.mkdir(parents=True, exist_ok=True)
    return iid


def full_database_copy() -> bytes:
    """Consistent copy of the whole SQLite file (for the server operator)."""
    import sqlite3
    import tempfile
    from pathlib import Path
    src = sqlite3.connect(db.db_path())
    with tempfile.TemporaryDirectory() as tmp:
        dst_path = Path(tmp) / "copy.sqlite3"
        dst = sqlite3.connect(dst_path)
        src.backup(dst)
        dst.close()
        src.close()
        return dst_path.read_bytes()
