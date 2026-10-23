"""Students, guardians, admissions, staff, CSV import, promotion and transfers."""
from __future__ import annotations

import io
import json
from datetime import date

import pandas as pd

from . import branding, db
from .accounts import ValidationError
from .actor import Actor, PermissionDenied

STUDENT_STATUSES = ["applicant", "active", "on_leave", "graduated", "transferred", "withdrawn", "archived"]
APPLICATION_STATUSES = ["draft", "submitted", "under_review", "accepted", "rejected", "waitlisted"]
GENDERS = ["Female", "Male", "Other"]
DOC_CHECKLIST = ["Birth certificate / ID", "Previous result card", "Transfer / leaving certificate",
                 "Passport-size photo", "Guardian ID copy", "Medical form"]
EMPLOYMENT_STATUSES = ["active", "on_leave", "resigned", "retired", "terminated"]


def full_name(row: dict) -> str:
    return f"{row.get('first_name', '')} {row.get('last_name') or ''}".strip()


def class_label(c: dict | None) -> str:
    if not c:
        return "—"
    return f"{c['name']}{(' – ' + c['section']) if c.get('section') else ''}"


def class_options(actor: Actor, only_scope: bool = True) -> dict[int, str]:
    T = actor.tenant
    scope = actor.class_scope() if only_scope else None
    rows = T.all("classes", "is_active=1", order="name, section")
    return {c["id"]: class_label(c) for c in rows if scope is None or c["id"] in scope}


# --------------------------------------------------------------------------- #
# Students
# --------------------------------------------------------------------------- #
def _clean_student(data: dict) -> dict:
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}
    if not data.get("first_name"):
        raise ValidationError("First name is required.")
    if data.get("dob"):
        if str(data["dob"]) > db.today():
            raise ValidationError("Date of birth cannot be in the future.")
    for k in ("dob", "admission_date"):
        if isinstance(data.get(k), date):
            data[k] = data[k].isoformat()
    return data


def create_student(actor: Actor, data: dict, guardian: dict | None = None) -> int:
    actor.require("students.manage")
    T = actor.tenant
    data = _clean_student(data)
    with db.transaction():
        if not data.get("admission_no"):
            data["admission_no"] = T.next_number("admission", actor.settings["admission_prefix"], 4)
        if T.one("students", "admission_no=?", (data["admission_no"],)):
            raise ValidationError(f"Admission number {data['admission_no']} is already used.")
        data.setdefault("status", "active")
        data.setdefault("admission_date", db.today())
        sid = T.insert("students", created_at=db.now(), **data)
        if data.get("class_id"):
            c = T.get("classes", data["class_id"])
            T.insert("enrollments", student_id=sid, class_id=data["class_id"],
                     program_id=data.get("program_id"), academic_year_id=c["academic_year_id"],
                     status="enrolled", created_at=db.now())
        if guardian and guardian.get("name", "").strip():
            link_guardian(actor, sid, guardian)
        actor.log("student_created", "student", sid, {"admission_no": data["admission_no"]})
    return sid


def update_student(actor: Actor, student_id: int, data: dict):
    actor.require("students.manage")
    T = actor.tenant
    old = T.require("students", student_id)
    data = _clean_student({**old, **data})
    for k in ("id", "institution_id", "created_at", "updated_at", "status", "class_id"):
        data.pop(k, None)  # status/class changes go through their own workflows
    if data["admission_no"] != old["admission_no"] and \
            T.one("students", "admission_no=? AND id<>?", (data["admission_no"], student_id)):
        raise ValidationError(f"Admission number {data['admission_no']} is already used.")
    T.update("students", student_id, updated_at=db.now(), **data)
    actor.log("student_updated", "student", student_id)


def link_guardian(actor: Actor, student_id: int, guardian: dict) -> int:
    """Link an existing guardian (guardian['id']) or create one. Siblings share
    the same guardian record instead of duplicating it."""
    actor.require("students.manage")
    T = actor.tenant
    T.require("students", student_id)
    gid = guardian.get("id")
    with db.transaction():
        if gid:
            T.require("guardians", gid)
        else:
            if not guardian.get("name", "").strip():
                raise ValidationError("Guardian name is required.")
            gid = None
            if guardian.get("phone"):  # reuse a guardian with the same name + phone (siblings)
                same = T.one("guardians", "lower(name)=lower(?) AND phone=?",
                             (guardian["name"].strip(), guardian["phone"].strip()))
                gid = same["id"] if same else None
            if not gid:
                gid = T.insert("guardians", name=guardian["name"].strip(),
                               phone=(guardian.get("phone") or "").strip(),
                               email=(guardian.get("email") or "").strip(),
                               address=(guardian.get("address") or "").strip(),
                               occupation=(guardian.get("occupation") or "").strip())
        if T.one("student_guardians", "student_id=? AND guardian_id=?", (student_id, gid)):
            return gid
        primary = guardian.get("is_primary", T.count("student_guardians", "student_id=?", (student_id,)) == 0)
        if primary:
            db.execute("UPDATE student_guardians SET is_primary=0 WHERE student_id=? AND institution_id=?",
                       (student_id, actor.iid))
        T.insert("student_guardians", student_id=student_id, guardian_id=gid,
                 relationship=guardian.get("relationship") or "Guardian", is_primary=int(bool(primary)))
    return gid


def siblings(T, student_id: int) -> list[dict]:
    return T.q("""
        SELECT DISTINCT st.id, st.admission_no, st.first_name, st.last_name, st.class_id
        FROM student_guardians a JOIN student_guardians b ON b.guardian_id=a.guardian_id
        JOIN students st ON st.id=b.student_id
        WHERE a.institution_id=:iid AND a.student_id=:s AND b.student_id<>:s
    """, {"s": int(student_id)})


def _apply_status(actor: Actor, student: dict, new_status: str, reason: str, new_class_id=None):
    T = actor.tenant
    T.update("students", student["id"], status=new_status, updated_at=db.now(),
             **({"class_id": new_class_id} if new_class_id else {}))
    T.insert("student_history", student_id=student["id"], event="status_change",
             from_value=student["status"], to_value=new_status, reason=reason,
             created_by=actor.uid, created_at=db.now())


def change_status(actor: Actor, student_id: int, new_status: str, reason: str) -> str:
    """Transfers and withdrawals need approval unless the actor can approve them.
    Returns 'applied' or 'pending'."""
    actor.require("students.manage", "students.approve_transfer")
    T = actor.tenant
    st = T.require("students", student_id)
    if new_status not in STUDENT_STATUSES:
        raise ValidationError("Unknown status.")
    if new_status == st["status"]:
        raise ValidationError("The student already has that status.")
    if len(reason.strip()) < 5:
        raise ValidationError("Give a reason (at least 5 characters).")
    needs_approval = new_status in ("transferred", "withdrawn")
    with db.transaction():
        if needs_approval and not actor.can("students.approve_transfer"):
            rid = T.insert("change_requests", request_type="status_change", student_id=student_id,
                           payload_json=json.dumps({"status": new_status}), reason=reason.strip(),
                           requested_by=actor.uid, created_at=db.now())
            actor.log("status_change_requested", "student", student_id, {"to": new_status})
            return "pending"
        _apply_status(actor, st, new_status, reason.strip())
        actor.log("student_status_changed", "student", student_id, {"from": st["status"], "to": new_status})
    return "applied"


def decide_change_request(actor: Actor, request_id: int, approve: bool):
    actor.require("students.approve_transfer")
    T = actor.tenant
    req = T.require("change_requests", request_id)
    if req["status"] != "pending":
        raise ValidationError("Already decided.")
    with db.transaction():
        if approve:
            payload = json.loads(req["payload_json"])
            st = T.require("students", req["student_id"])
            _apply_status(actor, st, payload["status"], req["reason"])
        T.update("change_requests", request_id, status="approved" if approve else "rejected",
                 decided_by=actor.uid, decided_at=db.now())
        actor.log("change_request_" + ("approved" if approve else "rejected"), "change_request", request_id)


def move_students(actor: Actor, student_ids: list[int], to_class_id: int, event: str = "promotion",
                  reason: str = "") -> int:
    """Promotion, section transfer or program/semester progression."""
    actor.require("students.manage")
    T = actor.tenant
    target = T.require("classes", to_class_id)
    n = 0
    with db.transaction():
        for sid in student_ids:
            st = T.require("students", sid)
            if st["class_id"] == target["id"]:
                continue
            old = class_label(T.get("classes", st["class_id"]))
            T.update("students", sid, class_id=target["id"],
                     academic_year_id=target["academic_year_id"] or st["academic_year_id"],
                     program_id=target["program_id"] or st["program_id"], updated_at=db.now())
            T.insert("student_history", student_id=sid, event=event, from_value=old,
                     to_value=class_label(target), reason=reason, created_by=actor.uid, created_at=db.now())
            existing = T.one("enrollments", "student_id=? AND class_id=? AND term_id IS NULL AND subject_id IS NULL",
                             (sid, target["id"]))
            if not existing:
                T.insert("enrollments", student_id=sid, class_id=target["id"], program_id=target["program_id"],
                         academic_year_id=target["academic_year_id"], status="enrolled", created_at=db.now())
            n += 1
        actor.log(f"students_{event}", "class", to_class_id, {"count": n})
    return n


def save_document(actor: Actor, filename: str, content: bytes, doc_type: str, *, student_id=None,
                  staff_id=None, application_id=None) -> int:
    actor.require("students.documents", "staff.manage", "admissions.manage")
    if staff_id and not actor.can("staff.manage"):
        raise PermissionDenied("Staff documents need the staff management permission.")
    data, ext, mime = branding.validate_document(filename, content)
    path = branding.save_file(actor.iid, "uploads", data, ext)
    did = actor.tenant.insert("documents", student_id=student_id, staff_id=staff_id,
                              application_id=application_id, doc_type=doc_type, file_path=path,
                              original_name=filename[:200], mime=mime, size=len(data),
                              uploaded_by=actor.uid, uploaded_at=db.now())
    actor.log("document_uploaded", "document", did, {"type": doc_type})
    return did


def read_document(actor: Actor, doc_id: int) -> tuple[bytes, dict]:
    doc = actor.tenant.require("documents", doc_id)
    if doc["staff_id"]:
        actor.require("staff.manage")
    else:
        actor.require("students.documents", "admissions.manage")
    data = branding.read_file(actor.iid, doc["file_path"])
    if data is None:
        raise ValidationError("The stored file is missing.")
    return data, doc


# --------------------------------------------------------------------------- #
# Admissions
# --------------------------------------------------------------------------- #
def create_application(actor: Actor, data: dict) -> int:
    actor.require("admissions.manage")
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}
    if not data.get("first_name"):
        raise ValidationError("Applicant first name is required.")
    if isinstance(data.get("dob"), date):
        data["dob"] = data["dob"].isoformat()
    T = actor.tenant
    with db.transaction():
        number = T.next_number("application", actor.settings["application_prefix"], 4)
        aid = T.insert("applications", application_no=number, created_by=actor.uid, created_at=db.now(),
                       documents_json=json.dumps(data.pop("documents", {})), **data)
        actor.log("application_created", "application", aid, {"no": number})
    return aid


def set_application_status(actor: Actor, app_id: int, status: str, notes: str = ""):
    actor.require("admissions.manage")
    T = actor.tenant
    app = T.require("applications", app_id)
    if status not in APPLICATION_STATUSES or status == "accepted":
        raise ValidationError("Use 'Accept & enrol' to accept an application.")
    if app["status"] == "accepted":
        raise ValidationError("This application has already been accepted.")
    T.update("applications", app_id, status=status, notes=notes or app["notes"],
             decided_by=actor.uid if status in ("rejected", "waitlisted") else app["decided_by"],
             decided_at=db.now() if status in ("rejected", "waitlisted") else app["decided_at"])
    actor.log("application_status", "application", app_id, {"status": status})


def accept_application(actor: Actor, app_id: int, class_id: int | None) -> int:
    """Accept and convert to an enrolled student with guardian and documents."""
    actor.require("admissions.manage")
    T = actor.tenant
    app = T.require("applications", app_id)
    if app["status"] == "accepted":
        raise ValidationError("Already accepted.")
    if app["status"] == "rejected":
        raise ValidationError("A rejected application cannot be accepted.")
    with db.transaction():
        cls = T.get("classes", class_id) if class_id else None
        sid = create_student(actor, {
            "first_name": app["first_name"], "last_name": app["last_name"], "gender": app["gender"],
            "dob": app["dob"], "email": app["email"], "phone": app["phone"], "address": app["address"],
            "previous_school": app["previous_school"], "class_id": class_id,
            "program_id": (cls or {}).get("program_id") or app["applied_program_id"],
            "academic_year_id": (cls or {}).get("academic_year_id"),
        }, guardian={"name": app["guardian_name"] or "", "phone": app["guardian_phone"] or "",
                     "relationship": app["guardian_relationship"] or "Guardian"})
        db.execute("UPDATE documents SET student_id=? WHERE application_id=? AND institution_id=?",
                   (sid, app_id, actor.iid))
        T.update("applications", app_id, status="accepted", student_id=sid, decided_by=actor.uid,
                 decided_at=db.now())
        actor.log("application_accepted", "application", app_id, {"student_id": sid})
    return sid


# --------------------------------------------------------------------------- #
# Staff
# --------------------------------------------------------------------------- #
def create_staff(actor: Actor, data: dict) -> int:
    actor.require("staff.manage")
    T = actor.tenant
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}
    if not data.get("full_name"):
        raise ValidationError("Full name is required.")
    if isinstance(data.get("joining_date"), date):
        data["joining_date"] = data["joining_date"].isoformat()
    with db.transaction():
        if not data.get("staff_no"):
            data["staff_no"] = T.next_number("staff", actor.settings["staff_prefix"], 4)
        if T.one("staff", "staff_no=?", (data["staff_no"],)):
            raise ValidationError(f"Staff number {data['staff_no']} is already used.")
        sid = T.insert("staff", created_at=db.now(), **data)
        actor.log("staff_created", "staff", sid, {"staff_no": data["staff_no"]})
    return sid


def update_staff(actor: Actor, staff_id: int, data: dict):
    actor.require("staff.manage")
    T = actor.tenant
    T.require("staff", staff_id)
    if isinstance(data.get("joining_date"), date):
        data["joining_date"] = data["joining_date"].isoformat()
    if data.get("staff_no") and T.one("staff", "staff_no=? AND id<>?", (data["staff_no"], staff_id)):
        raise ValidationError("That staff number is already used.")
    T.update("staff", staff_id, **data)
    actor.log("staff_updated", "staff", staff_id)


def assign_teacher(actor: Actor, staff_id: int, class_id: int, subject_id: int | None):
    actor.require("academics.manage")
    T = actor.tenant
    T.require("staff", staff_id)
    T.require("classes", class_id)
    if T.one("teacher_assignments", "staff_id=? AND class_id=? AND IFNULL(subject_id,0)=?",
             (staff_id, class_id, int(subject_id or 0))):
        raise ValidationError("That assignment already exists.")
    aid = T.insert("teacher_assignments", staff_id=staff_id, class_id=class_id, subject_id=subject_id)
    actor.log("teacher_assigned", "teacher_assignment", aid)
    return aid


def workload(T) -> pd.DataFrame:
    rows = T.q("""
        SELECT s.staff_no, s.full_name, s.designation,
               (SELECT COUNT(*) FROM teacher_assignments ta WHERE ta.staff_id=s.id) AS assignments,
               (SELECT COUNT(*) FROM timetable t WHERE t.staff_id=s.id) AS weekly_periods,
               (SELECT COUNT(*) FROM classes c WHERE c.class_teacher_id=s.id) AS class_teacher_of
        FROM staff s WHERE s.institution_id=:iid AND s.employment_status='active'
        ORDER BY weekly_periods DESC, s.full_name
    """)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Bulk CSV import with preview and per-row errors
# --------------------------------------------------------------------------- #
IMPORT_COLUMNS = ["admission_no", "first_name", "last_name", "gender", "dob", "class", "section",
                  "phone", "email", "address", "guardian_name", "guardian_phone", "guardian_relationship"]


def import_template() -> bytes:
    sample = pd.DataFrame([{
        "admission_no": "", "first_name": "Ayesha", "last_name": "Khan", "gender": "Female",
        "dob": "2012-04-18", "class": "Grade 7", "section": "A", "phone": "0300-0000000",
        "email": "", "address": "Street 1, City", "guardian_name": "Imran Khan",
        "guardian_phone": "0300-1111111", "guardian_relationship": "Father"}], columns=IMPORT_COLUMNS)
    return sample.to_csv(index=False).encode("utf-8-sig")


def preview_import(actor: Actor, raw: bytes) -> pd.DataFrame:
    """Parse and validate without saving. Adds 'errors' and 'class_id' columns."""
    T = actor.tenant
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except Exception as exc:
        raise ValidationError(f"Could not read the CSV file: {exc}") from exc
    if len(df) > 2000:
        raise ValidationError("Import at most 2000 rows at a time.")
    df.columns = [c.strip().lower() for c in df.columns]
    if "first_name" not in df.columns:
        raise ValidationError("The CSV needs at least a 'first_name' column. Download the template.")
    for c in IMPORT_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df = df[IMPORT_COLUMNS].apply(lambda col: col.str.strip())
    classes = {(c["name"].strip().lower(), (c["section"] or "").strip().lower()): c["id"]
               for c in T.all("classes")}
    used = {r["admission_no"] for r in T.q("SELECT admission_no FROM students WHERE institution_id=:iid")}
    seen, errors, class_ids = set(), [], []
    for _, r in df.iterrows():
        e = []
        if not r["first_name"]:
            e.append("first_name is required")
        if r["gender"] and r["gender"].title() not in GENDERS:
            e.append("gender must be Female/Male/Other")
        if r["dob"]:
            try:
                d = date.fromisoformat(r["dob"])
                if d > date.today():
                    e.append("dob is in the future")
            except ValueError:
                e.append("dob must be YYYY-MM-DD")
        cid = None
        if r["class"]:
            cid = classes.get((r["class"].lower(), r["section"].lower()))
            if not cid:
                e.append(f"class '{r['class']} {r['section']}' not found")
        if r["admission_no"]:
            if r["admission_no"] in used:
                e.append("admission_no already exists")
            if r["admission_no"] in seen:
                e.append("admission_no repeated in file")
            seen.add(r["admission_no"])
        if r["guardian_phone"] and not r["guardian_name"]:
            e.append("guardian_name missing")
        errors.append("; ".join(e))
        class_ids.append(cid)
    df["class_id"] = pd.Series(class_ids, index=df.index, dtype=object)
    df["errors"] = errors
    return df


def commit_import(actor: Actor, df: pd.DataFrame) -> int:
    actor.require("students.import")
    actor.require("students.manage")
    ok = df[df["errors"] == ""]
    n = 0
    with db.transaction():
        for _, r in ok.iterrows():
            cls = actor.tenant.get("classes", r["class_id"]) if r["class_id"] else None
            create_student(actor, {
                "admission_no": r["admission_no"] or None, "first_name": r["first_name"],
                "last_name": r["last_name"], "gender": r["gender"].title() or None,
                "dob": r["dob"] or None, "class_id": int(r["class_id"]) if r["class_id"] else None,
                "program_id": (cls or {}).get("program_id"), "academic_year_id": (cls or {}).get("academic_year_id"),
                "phone": r["phone"], "email": r["email"], "address": r["address"],
            }, guardian={"name": r["guardian_name"], "phone": r["guardian_phone"],
                         "relationship": r["guardian_relationship"] or "Guardian"})
            n += 1
        actor.log("students_imported", "student", None, {"rows": n})
    return n
