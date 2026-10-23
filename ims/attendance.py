"""Student/staff attendance, leave, timetable conflict detection."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from . import db
from .accounts import ValidationError
from .actor import Actor, PermissionDenied

STATUSES = ["present", "absent", "late", "excused", "leave"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def save_attendance(actor: Actor, day: str, class_id: int, subject_id: int | None,
                    marks: dict[int, tuple[str, str]], reason: str = "") -> dict:
    """marks: {student_id: (status, remark)}.

    Same-day edits by the person who marked are free. Changing any other
    existing record is a correction: it needs ``attendance.correct`` and a
    reason, and leaves an audit row.
    """
    actor.require("attendance.mark")
    actor.check_class(class_id)
    T = actor.tenant
    T.require("classes", class_id)
    if subject_id:
        T.require("subjects", subject_id)
    if day > db.today():
        raise ValidationError("Attendance cannot be marked for a future date.")
    valid = {s["id"] for s in T.all("students", "class_id=? AND status='active'", (int(class_id),))}
    stats = {"inserted": 0, "updated": 0, "corrected": 0}
    with db.transaction():
        for sid, (status, remark) in marks.items():
            sid = int(sid)
            if sid not in valid:
                raise PermissionDenied("A student in the list is not in this class.")
            if status not in STATUSES:
                raise ValidationError(f"Invalid status '{status}'.")
            existing = T.one("attendance", "student_id=? AND date=? AND IFNULL(subject_id,0)=?",
                             (sid, day, int(subject_id or 0)))
            if not existing:
                T.insert("attendance", student_id=sid, date=day, subject_id=subject_id, status=status,
                         remark=remark, marked_by=actor.uid, marked_at=db.now())
                stats["inserted"] += 1
                continue
            if existing["status"] == status and (existing["remark"] or "") == (remark or ""):
                continue
            free_edit = day == db.today() and existing["marked_by"] == actor.uid
            if existing["status"] != status and not free_edit:
                if not actor.can("attendance.correct"):
                    raise PermissionDenied("Changing earlier attendance needs the 'correct attendance' "
                                           "permission.")
                if len(reason.strip()) < 5:
                    raise ValidationError("Enter a correction reason (at least 5 characters).")
                T.insert("attendance_corrections", attendance_id=existing["id"],
                         old_status=existing["status"], new_status=status, reason=reason.strip(),
                         created_by=actor.uid, created_at=db.now())
                stats["corrected"] += 1
            T.update("attendance", existing["id"], status=status, remark=remark,
                     marked_by=actor.uid, marked_at=db.now())
            stats["updated"] += 1
        actor.log("attendance_saved", "class", class_id,
                  {"date": day, "subject_id": subject_id, **stats})
    return stats


def percentages(T, start: str, end: str, class_id: int | None = None,
                student_ids: list[int] | None = None) -> pd.DataFrame:
    """Attendance % per student. Present and late count as attended; excused
    and leave days are left out of the total."""
    sql = """
        SELECT st.id AS student_id, st.admission_no,
               st.first_name || ' ' || IFNULL(st.last_name,'') AS student, st.class_id,
               SUM(a.status IN ('present','late')) AS attended,
               SUM(a.status = 'absent') AS absent,
               SUM(a.status = 'late') AS late,
               SUM(a.status IN ('excused','leave')) AS excused,
               COUNT(a.id) AS marked
        FROM students st
        LEFT JOIN attendance a ON a.student_id=st.id AND a.date BETWEEN :a AND :b
        WHERE st.institution_id=:iid AND st.status='active'
    """
    params = {"a": start, "b": end}
    if class_id:
        sql += " AND st.class_id=:c"
        params["c"] = int(class_id)
    if student_ids is not None:
        if not student_ids:
            return pd.DataFrame()
        sql += f" AND st.id IN ({','.join(str(int(i)) for i in student_ids)})"
    sql += " GROUP BY st.id ORDER BY st.first_name"
    df = pd.DataFrame(T.q(sql, params))
    if df.empty:
        return df
    counted = df["marked"] - df["excused"]
    df["percent"] = (df["attended"] / counted.where(counted > 0) * 100).round(1)
    return df


def daily_summary(T, day: str) -> dict:
    rows = T.q("SELECT status, COUNT(DISTINCT student_id) AS n FROM attendance "
               "WHERE institution_id=:iid AND date=:d GROUP BY status", {"d": day})
    return {r["status"]: r["n"] for r in rows}


def trend(T, days: int = 30) -> pd.DataFrame:
    start = (date.today() - timedelta(days=days)).isoformat()
    rows = T.q("""
        SELECT date, ROUND(100.0 * SUM(status IN ('present','late')) /
               NULLIF(SUM(status NOT IN ('excused','leave')),0), 1) AS rate
        FROM attendance WHERE institution_id=:iid AND date>=:s GROUP BY date ORDER BY date
    """, {"s": start})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Leave
# --------------------------------------------------------------------------- #
def working_days_between(a: date, b: date, working: list[str]) -> int:
    n = 0
    d = a
    while d <= b:
        if DAYS[d.weekday()] in working:
            n += 1
        d += timedelta(days=1)
    return n


def leave_balance(T, staff_id: int, settings: dict, year: int | None = None) -> dict:
    year = year or date.today().year
    used = T.q("SELECT leave_type, SUM(days) AS d FROM leave_requests WHERE institution_id=:iid "
               "AND staff_id=:s AND status='approved' AND substr(from_date,1,4)=:y GROUP BY leave_type",
               {"s": int(staff_id), "y": str(year)})
    used_map = {r["leave_type"]: r["d"] for r in used}
    return {k: {"allowed": v, "used": used_map.get(k, 0), "left": v - used_map.get(k, 0)}
            for k, v in settings["leave_allowance"].items()}


def request_leave(actor: Actor, leave_type: str, start: date, end: date, reason: str) -> int:
    actor.require("leave.request")
    staff = actor.staff_row()
    if not staff:
        raise ValidationError("Your login is not linked to a staff record.")
    if end < start:
        raise ValidationError("The end date is before the start date.")
    s = actor.settings
    if leave_type not in s["leave_allowance"]:
        raise ValidationError("Unknown leave type.")
    days = working_days_between(start, end, s["working_days"])
    if days == 0:
        raise ValidationError("The selected dates contain no working days.")
    bal = leave_balance(actor.tenant, staff["id"], s, start.year)[leave_type]
    if days > bal["left"]:
        raise ValidationError(f"Only {bal['left']:g} {leave_type.lower()} day(s) left this year.")
    overlap = actor.tenant.one("leave_requests", "staff_id=? AND status IN ('pending','approved') "
                                                 "AND from_date<=? AND to_date>=?",
                               (staff["id"], end.isoformat(), start.isoformat()))
    if overlap:
        raise ValidationError("You already have leave covering some of these dates.")
    lid = actor.tenant.insert("leave_requests", staff_id=staff["id"], leave_type=leave_type,
                              from_date=start.isoformat(), to_date=end.isoformat(), days=days,
                              reason=reason.strip(), created_at=db.now())
    actor.log("leave_requested", "leave", lid, {"days": days, "type": leave_type})
    return lid


def decide_leave(actor: Actor, leave_id: int, approve: bool):
    actor.require("leave.approve")
    T = actor.tenant
    lv = T.require("leave_requests", leave_id)
    if lv["status"] != "pending":
        raise ValidationError("Already decided.")
    staff = actor.staff_row()
    if staff and staff["id"] == lv["staff_id"]:
        raise PermissionDenied("You cannot approve your own leave.")
    with db.transaction():
        T.update("leave_requests", leave_id, status="approved" if approve else "rejected",
                 decided_by=actor.uid, decided_at=db.now())
        if approve:  # mark the staff attendance register as leave for those days
            d, end = date.fromisoformat(lv["from_date"]), date.fromisoformat(lv["to_date"])
            while d <= end:
                row = T.one("staff_attendance", "staff_id=? AND date=?", (lv["staff_id"], d.isoformat()))
                if row:
                    T.update("staff_attendance", row["id"], status="leave", remark="Approved leave")
                else:
                    T.insert("staff_attendance", staff_id=lv["staff_id"], date=d.isoformat(),
                             status="leave", remark="Approved leave", marked_by=actor.uid)
                d += timedelta(days=1)
        actor.log("leave_approved" if approve else "leave_rejected", "leave", leave_id)


# --------------------------------------------------------------------------- #
# Timetable
# --------------------------------------------------------------------------- #
def timetable_conflicts(T, day: str, period: int, class_id: int, staff_id: int | None,
                        room: str, exclude_id: int = 0) -> list[str]:
    found = []
    rows = T.q("""
        SELECT t.*, c.name AS class_name, c.section, s.full_name AS teacher
        FROM timetable t JOIN classes c ON c.id=t.class_id LEFT JOIN staff s ON s.id=t.staff_id
        WHERE t.institution_id=:iid AND t.day=:d AND t.period=:p AND t.id<>:x
    """, {"d": day, "p": int(period), "x": int(exclude_id)})
    for r in rows:
        label = f"{r['class_name']} {r['section'] or ''}".strip()
        if r["class_id"] == int(class_id):
            found.append(f"{label} already has a lesson in period {period} on {day}.")
        if staff_id and r["staff_id"] == int(staff_id):
            found.append(f"{r['teacher']} is already teaching {label} at that time.")
        if room and (r["room"] or "").strip().lower() == room.strip().lower():
            found.append(f"Room {room} is already used by {label}.")
    return found


def add_timetable_entry(actor: Actor, *, class_id: int, subject_id: int | None, staff_id: int | None,
                        room: str, day: str, period: int, start_time: str = "", end_time: str = "") -> int:
    actor.require("timetable.manage")
    if day not in DAYS:
        raise ValidationError("Invalid day.")
    conflicts = timetable_conflicts(actor.tenant, day, period, class_id, staff_id, room)
    if conflicts:
        raise ValidationError(" ".join(conflicts))
    tid = actor.tenant.insert("timetable", class_id=class_id, subject_id=subject_id, staff_id=staff_id,
                              room=room.strip(), day=day, period=int(period),
                              start_time=start_time, end_time=end_time)
    actor.log("timetable_added", "timetable", tid)
    return tid


def scan_conflicts(T) -> list[str]:
    issues = []
    for col, label in (("staff_id", "Teacher"), ("class_id", "Class"), ("lower(room)", "Room")):
        rows = T.q(f"""
            SELECT day, period, {col} AS k, COUNT(*) AS n FROM timetable
            WHERE institution_id=:iid AND {col} IS NOT NULL AND {col} <> ''
            GROUP BY day, period, {col} HAVING COUNT(*) > 1
        """)
        for r in rows:
            issues.append(f"{label} double-booked on {r['day']} period {r['period']} ({r['n']} lessons).")
    return issues
