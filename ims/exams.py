"""Grading, marks entry and the result approval workflow.

Workflow per marksheet (exam × class × subject):
draft → submitted (teacher) → reviewed (exam coordinator) → approved (principal)
→ published. Approved/published marks are locked; changing them needs
``results.correct``, a reason and leaves a correction record.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from . import db
from .accounts import ValidationError
from .actor import Actor, PermissionDenied

WORKFLOW = ["draft", "submitted", "reviewed", "approved", "published"]
EXAM_TYPES = ["quiz", "assignment", "midterm", "final", "practical", "supplementary"]


# --------------------------------------------------------------------------- #
# Grading
# --------------------------------------------------------------------------- #
def grade_for(pct: float, scale: list[dict]) -> tuple[str, float]:
    for band in sorted(scale, key=lambda b: -float(b["min"])):
        if pct >= float(band["min"]) - 1e-9:
            return band["grade"], float(band["point"])
    return "F", 0.0


def validate_scale(scale: list[dict]):
    mins = [float(b["min"]) for b in scale]
    if not scale or min(mins) != 0:
        raise ValidationError("The grading scale needs a band that starts at 0%.")
    if len(set(mins)) != len(mins):
        raise ValidationError("Each grade band needs a different minimum percentage.")
    for b in scale:
        if not str(b["grade"]).strip():
            raise ValidationError("Every band needs a grade label.")
        if not (0 <= float(b["min"]) <= 100) or not (0 <= float(b["point"]) <= 10):
            raise ValidationError("Minimums must be 0–100 and grade points 0–10.")


def subject_results(rows: list[dict], scale, pass_pct: float) -> list[dict]:
    """Combine one student's exam rows into one line per subject.

    Regular exams are weighted by their weightage. A supplementary (re-sit)
    result replaces the subject percentage when it is higher. Absent counts as
    zero; exempt subjects are listed but excluded from GPA and pass/fail.
    """
    by_subject = defaultdict(list)
    for r in rows:
        by_subject[r["subject_id"]].append(r)
    out = []
    for sid, items in by_subject.items():
        first = items[0]
        regular = [r for r in items if r["exam_type"] != "supplementary" and not r["is_exempt"]]
        supp = [r for r in items if r["exam_type"] == "supplementary" and not r["is_exempt"]]
        exempt = all(r["is_exempt"] for r in items)
        pct = None
        if regular:
            wsum = sum(float(r["weightage"]) for r in regular)
            pct = sum(float(r["weightage"]) * (float(r["obtained_marks"] or 0) / float(r["max_marks"]))
                      for r in regular) / wsum * 100
        if supp:
            spct = max(float(r["obtained_marks"] or 0) / float(r["max_marks"]) * 100 for r in supp)
            pct = spct if pct is None else max(pct, spct)
        line = {
            "subject_id": sid, "subject": first["subject_name"], "code": first.get("subject_code") or "",
            "credit_hours": float(first.get("credit_hours") or 1),
            "obtained": sum(float(r["obtained_marks"] or 0) for r in regular),
            "max": sum(float(r["max_marks"]) for r in regular),
            "exempt": exempt, "absent": any(r["is_absent"] for r in items),
        }
        if exempt or pct is None:
            line.update(percent=None, grade="EX", point=None, passed=None)
        else:
            g, p = grade_for(pct, scale)
            line.update(percent=round(pct, 2), grade=g, point=p, passed=pct >= pass_pct)
        out.append(line)
    return sorted(out, key=lambda x: x["subject"])


def gpa(lines: list[dict]) -> float | None:
    graded = [l for l in lines if l["point"] is not None]
    credits = sum(l["credit_hours"] for l in graded)
    if not credits:
        return None
    return round(sum(l["point"] * l["credit_hours"] for l in graded) / credits, 2)


def _result_rows(T, student_id: int, term_id: int | None = None, published_only=True):
    sql = """
        SELECT r.*, e.exam_type, e.weightage, e.name AS exam_name, e.term_id,
               s.name AS subject_name, s.code AS subject_code, s.credit_hours
        FROM results r
        JOIN marksheets m ON m.id = r.marksheet_id
        JOIN exams e ON e.id = r.exam_id
        JOIN subjects s ON s.id = r.subject_id
        WHERE r.institution_id=:iid AND r.student_id=:sid
          AND (r.obtained_marks IS NOT NULL OR r.is_absent=1 OR r.is_exempt=1)
    """
    params = {"sid": int(student_id)}
    if term_id:
        sql += " AND e.term_id=:tid"
        params["tid"] = int(term_id)
    if published_only:
        sql += " AND m.status='published'"
    return T.q(sql, params)


def term_report(actor_or_T, settings: dict, student_id: int, term_id: int,
                published_only=True) -> dict:
    T = actor_or_T.tenant if isinstance(actor_or_T, Actor) else actor_or_T
    lines = subject_results(_result_rows(T, student_id, term_id, published_only),
                            settings["grading_scale"], float(settings["pass_percent"]))
    graded = [l for l in lines if l["percent"] is not None]
    total_obt = sum(l["obtained"] for l in graded)
    total_max = sum(l["max"] for l in graded)
    return {
        "lines": lines,
        "gpa": gpa(lines),
        "percent": round(sum(l["percent"] for l in graded) / len(graded), 2) if graded else None,
        "total_obtained": total_obt, "total_max": total_max,
        "failed": [l["subject"] for l in graded if l["passed"] is False],
        "result": ("Pass" if graded and all(l["passed"] for l in graded) else
                   ("Fail" if graded else "No published results")),
    }


def transcript(T, settings: dict, student_id: int) -> dict:
    terms = T.q("""
        SELECT DISTINCT t.id, t.name, t.start_date, y.name AS year
        FROM results r JOIN exams e ON e.id=r.exam_id JOIN terms t ON t.id=e.term_id
        JOIN marksheets m ON m.id=r.marksheet_id
        LEFT JOIN academic_years y ON y.id=t.academic_year_id
        WHERE r.institution_id=:iid AND r.student_id=:sid AND m.status='published'
        ORDER BY t.start_date
    """, {"sid": int(student_id)})
    out, all_lines = [], []
    for t in terms:
        rep = term_report(T, settings, student_id, t["id"])
        credits = sum(l["credit_hours"] for l in rep["lines"] if l["point"] is not None)
        earned = sum(l["credit_hours"] for l in rep["lines"] if l["passed"])
        all_lines += rep["lines"]
        out.append({"term": t, "report": rep, "credits": credits, "earned": earned,
                    "cgpa": gpa(all_lines)})
    cg = gpa(all_lines)
    standing = None
    if cg is not None:
        standing = "Good standing" if cg >= float(settings.get("standing_min_gpa", 2.0)) else "Academic probation"
    return {"terms": out, "cgpa": cg, "standing": standing,
            "credits_earned": sum(t["earned"] for t in out)}


# --------------------------------------------------------------------------- #
# Marksheets
# --------------------------------------------------------------------------- #
def class_students(T, class_id: int) -> list[dict]:
    return T.all("students", "class_id=? AND status='active'", (int(class_id),),
                 order="first_name, last_name")


def get_or_create_marksheet(actor: Actor, exam_id: int, class_id: int, subject_id: int) -> dict:
    T = actor.tenant
    T.require("exams", exam_id)
    subj = T.require("subjects", subject_id)
    T.require("classes", class_id)
    ms = T.one("marksheets", "exam_id=? AND class_id=? AND subject_id=?",
               (int(exam_id), int(class_id), int(subject_id)))
    if ms:
        return ms
    _check_marks_scope(actor, class_id, subject_id)
    mid = T.insert("marksheets", exam_id=exam_id, class_id=class_id, subject_id=subject_id,
                   max_marks=subj["max_marks"], status="draft")
    return T.get("marksheets", mid)


def _check_marks_scope(actor: Actor, class_id: int, subject_id: int):
    if actor.can("exams.manage") and actor.can("classes.all"):
        return
    actor.require("marks.enter")
    actor.check_class(class_id)
    scope = actor.subject_scope(class_id)
    if scope is not None and int(subject_id) not in scope:
        raise PermissionDenied("This subject is not assigned to you for this class.")


def marksheet_frame(actor: Actor, ms: dict) -> pd.DataFrame:
    T = actor.tenant
    students = class_students(T, ms["class_id"])
    existing = {r["student_id"]: r for r in T.all("results", "marksheet_id=?", (ms["id"],))}
    rows = []
    for s in students:
        r = existing.get(s["id"], {})
        rows.append({
            "student_id": s["id"], "Admission no": s["admission_no"],
            "Student": f"{s['first_name']} {s['last_name']}".strip(),
            "Marks": r.get("obtained_marks"), "Absent": bool(r.get("is_absent", 0)),
            "Exempt": bool(r.get("is_exempt", 0)), "Remarks": r.get("remarks") or "",
            "Grade": r.get("grade") or "",
        })
    return pd.DataFrame(rows)


def save_marks(actor: Actor, marksheet_id: int, entries: list[dict]) -> int:
    """entries: dicts with student_id, marks, absent, exempt, remarks."""
    T = actor.tenant
    ms = T.require("marksheets", marksheet_id)
    _check_marks_scope(actor, ms["class_id"], ms["subject_id"])
    if ms["status"] != "draft":
        raise ValidationError("Only draft marksheets can be edited. Ask a reviewer to return it, "
                              "or use the correction workflow for approved results.")
    settings = actor.settings
    valid_students = {s["id"] for s in class_students(T, ms["class_id"])}
    max_marks = float(ms["max_marks"])
    errors, saved = [], 0
    clean = []
    for e in entries:
        sid = int(e["student_id"])
        if sid not in valid_students:
            raise PermissionDenied("A student in the list is not in this class.")
        marks = e.get("marks")
        marks = None if marks is None or (isinstance(marks, float) and pd.isna(marks)) else float(marks)
        absent, exempt = bool(e.get("absent")), bool(e.get("exempt"))
        if absent and exempt:
            errors.append(f"{e.get('name', sid)}: cannot be both absent and exempt")
            continue
        if absent or exempt:
            marks = 0.0 if absent else None
        if marks is not None and not (0 <= marks <= max_marks):
            errors.append(f"{e.get('name', sid)}: marks must be between 0 and {max_marks:g}")
            continue
        clean.append((sid, marks, absent, exempt, (e.get("remarks") or "").strip()))
    if errors:
        raise ValidationError("; ".join(errors))
    with db.transaction():
        for sid, marks, absent, exempt, remarks in clean:
            grade = point = None
            if marks is not None and not exempt:
                grade, point = grade_for(marks / max_marks * 100, settings["grading_scale"])
            row = T.one("results", "marksheet_id=? AND student_id=?", (ms["id"], sid))
            data = dict(obtained_marks=marks, is_absent=int(absent), is_exempt=int(exempt),
                        grade=grade, grade_point=point, remarks=remarks, max_marks=max_marks)
            if row:
                T.update("results", row["id"], **data)
            else:
                T.insert("results", marksheet_id=ms["id"], exam_id=ms["exam_id"], student_id=sid,
                         subject_id=ms["subject_id"], **data)
            saved += 1
        actor.log("marks_saved", "marksheet", ms["id"], {"rows": saved})
    return saved


def missing_marks(T, ms: dict) -> list[str]:
    students = class_students(T, ms["class_id"])
    have = {r["student_id"] for r in T.all("results", "marksheet_id=? AND (obtained_marks IS NOT NULL "
                                                      "OR is_absent=1 OR is_exempt=1)", (ms["id"],))}
    return [f"{s['first_name']} {s['last_name']}".strip() for s in students if s["id"] not in have]


TRANSITIONS = {
    "submit": ("draft", "submitted", None),
    "review": ("submitted", "reviewed", "results.review"),
    "approve": ("reviewed", "approved", "results.approve"),
    "publish": ("approved", "published", "results.publish"),
}


def transition(actor: Actor, marksheet_id: int, action: str, reason: str = ""):
    T = actor.tenant
    ms = T.require("marksheets", marksheet_id)
    if action == "return":
        actor.require("results.review", "results.approve")
        if ms["status"] not in ("submitted", "reviewed"):
            raise ValidationError("Only submitted or reviewed marksheets can be returned.")
        if len(reason.strip()) < 5:
            raise ValidationError("Give a reason (at least 5 characters) when returning marks.")
        T.update("marksheets", ms["id"], status="draft", return_reason=reason.strip())
        actor.log("marksheet_returned", "marksheet", ms["id"], {"reason": reason})
        return
    if action not in TRANSITIONS:
        raise ValidationError("Unknown action.")
    src, dst, perm = TRANSITIONS[action]
    if perm:
        actor.require(perm)
    else:
        _check_marks_scope(actor, ms["class_id"], ms["subject_id"])
    if ms["status"] != src:
        raise ValidationError(f"This marksheet is '{ms['status']}', not '{src}'.")
    if not perm:
        missing = missing_marks(T, ms)
        if missing:
            raise ValidationError(f"Marks missing for {len(missing)} student(s): "
                                  + ", ".join(missing[:8]) + ("…" if len(missing) > 8 else ""))
    stamp = {"submit": "submitted", "review": "reviewed", "approve": "approved",
             "publish": "published"}[action]
    T.update("marksheets", ms["id"], status=dst, return_reason=None,
             **{f"{stamp}_by": actor.uid, f"{stamp}_at": db.now()})
    actor.log(f"marksheet_{dst}", "marksheet", ms["id"])


def correct_result(actor: Actor, result_id: int, new_marks: float | None, absent: bool, reason: str):
    actor.require("results.correct")
    T = actor.tenant
    res = T.require("results", result_id)
    ms = T.require("marksheets", res["marksheet_id"])
    if ms["status"] not in ("approved", "published"):
        raise ValidationError("Draft or in-review marks are edited directly on the marksheet.")
    if len(reason.strip()) < 5:
        raise ValidationError("A correction needs a reason (at least 5 characters).")
    max_marks = float(res["max_marks"])
    marks = 0.0 if absent else (None if new_marks is None else float(new_marks))
    if marks is None or not (0 <= marks <= max_marks):
        raise ValidationError(f"Marks must be between 0 and {max_marks:g}.")
    grade, point = grade_for(marks / max_marks * 100, actor.settings["grading_scale"])
    old = f"{res['obtained_marks']}{' (absent)' if res['is_absent'] else ''}"
    new = f"{marks}{' (absent)' if absent else ''}"
    with db.transaction():
        T.update("results", result_id, obtained_marks=marks, is_absent=int(absent),
                 grade=grade, grade_point=point)
        T.insert("result_corrections", result_id=result_id, old_value=old, new_value=new,
                 reason=reason.strip(), created_by=actor.uid, created_at=db.now())
        actor.log("result_corrected", "result", result_id, {"old": old, "new": new, "reason": reason})


def class_result_sheet(T, settings: dict, exam_id: int, class_id: int,
                       published_only: bool = False) -> pd.DataFrame:
    """Students × subjects for one exam, with total, percentage, grade and position."""
    sql = """
        SELECT r.student_id, st.admission_no, st.first_name || ' ' || IFNULL(st.last_name,'') AS student,
               s.name AS subject, r.obtained_marks, r.max_marks, r.is_absent, r.is_exempt
        FROM results r JOIN marksheets m ON m.id=r.marksheet_id
        JOIN students st ON st.id=r.student_id JOIN subjects s ON s.id=r.subject_id
        WHERE r.institution_id=:iid AND m.exam_id=:e AND m.class_id=:c
    """
    if published_only:
        sql += " AND m.status='published'"
    rows = T.q(sql, {"e": int(exam_id), "c": int(class_id)})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["shown"] = df.apply(lambda r: "EX" if r.is_exempt else ("AB" if r.is_absent else r.obtained_marks), axis=1)
    wide = df.pivot_table(index=["student_id", "admission_no", "student"], columns="subject",
                          values="shown", aggfunc="first").reset_index()
    counted = df[df.is_exempt == 0]
    totals = counted.groupby("student_id").agg(obt=("obtained_marks", lambda x: x.fillna(0).sum()),
                                               mx=("max_marks", "sum"))
    wide = wide.merge(totals, left_on="student_id", right_index=True, how="left")
    wide["Total"] = wide["obt"].round(2)
    wide["Max"] = wide["mx"]
    wide["%"] = (wide["obt"] / wide["mx"] * 100).round(2)
    wide["Grade"] = wide["%"].apply(lambda p: grade_for(p, settings["grading_scale"])[0] if pd.notna(p) else "")
    wide["Position"] = wide["%"].rank(ascending=False, method="min").astype("Int64")
    wide = wide.drop(columns=["obt", "mx"]).sort_values("Position")
    return wide.rename(columns={"admission_no": "Admission no", "student": "Student"})
