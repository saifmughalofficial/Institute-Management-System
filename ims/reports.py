"""Report builders. Each returns a DataFrame that the Reports page can show and
export; every query is scoped to the actor's institution (and class scope)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from . import attendance, fees, people
from .actor import Actor


@dataclass
class Report:
    key: str
    title: str
    group: str
    perm: str
    needs: tuple  # which filters to show: dates, class, exam, term, student
    build: Callable[[Actor, dict], pd.DataFrame]


def _scope_sql(actor: Actor, col: str = "st.class_id") -> str:
    scope = actor.class_scope()
    if scope is None:
        return ""
    return f" AND {col} IN ({','.join(str(i) for i in scope) or '0'})"


def _class_filter(f: dict, col="st.class_id") -> tuple[str, dict]:
    if f.get("class_id"):
        return f" AND {col}=:cid", {"cid": int(f["class_id"])}
    return "", {}


def student_directory(a: Actor, f):
    where, p = _class_filter(f)
    rows = a.tenant.q(f"""
        SELECT st.admission_no AS "Admission no", st.first_name || ' ' || IFNULL(st.last_name,'') AS "Student",
               st.gender AS "Gender", st.dob AS "DOB", c.name || IFNULL(' - ' || NULLIF(c.section,''),'') AS "Class",
               pr.name AS "Program", st.phone AS "Phone", st.email AS "Email", st.status AS "Status",
               (SELECT g.name || ' (' || IFNULL(g.phone,'') || ')' FROM student_guardians sg JOIN guardians g ON g.id=sg.guardian_id
                 WHERE sg.student_id=st.id ORDER BY sg.is_primary DESC LIMIT 1) AS "Primary guardian"
        FROM students st LEFT JOIN classes c ON c.id=st.class_id LEFT JOIN programs pr ON pr.id=st.program_id
        WHERE st.institution_id=:iid {where} {_scope_sql(a)}
        ORDER BY c.name, c.section, st.first_name
    """, p)
    return pd.DataFrame(rows)


def admission_register(a: Actor, f):
    rows = a.tenant.q(f"""
        SELECT st.admission_date AS "Admitted", st.admission_no AS "Admission no",
               st.first_name || ' ' || IFNULL(st.last_name,'') AS "Student",
               c.name || IFNULL(' - ' || NULLIF(c.section,''),'') AS "Class", st.previous_school AS "Previous school",
               st.status AS "Status"
        FROM students st LEFT JOIN classes c ON c.id=st.class_id
        WHERE st.institution_id=:iid AND st.admission_date BETWEEN :a AND :b {_scope_sql(a)}
        ORDER BY st.admission_date
    """, {"a": f["start"], "b": f["end"]})
    return pd.DataFrame(rows)


def status_report(a: Actor, f):
    rows = a.tenant.q(f"""
        SELECT IFNULL(c.name || IFNULL(' - ' || NULLIF(c.section,''),''), 'Unassigned') AS "Class",
               SUM(st.status='active') AS "Active", SUM(st.status='on_leave') AS "On leave",
               SUM(st.status='graduated') AS "Graduated", SUM(st.status='transferred') AS "Transferred",
               SUM(st.status='withdrawn') AS "Withdrawn", COUNT(*) AS "Total"
        FROM students st LEFT JOIN classes c ON c.id=st.class_id
        WHERE st.institution_id=:iid {_scope_sql(a)}
        GROUP BY st.class_id ORDER BY "Class"
    """)
    return pd.DataFrame(rows)


def attendance_register(a: Actor, f):
    where, p = _class_filter(f)
    rows = a.tenant.q(f"""
        SELECT a.date, st.admission_no, st.first_name || ' ' || IFNULL(st.last_name,'') AS student, a.status
        FROM attendance a JOIN students st ON st.id=a.student_id
        WHERE a.institution_id=:iid AND a.subject_id IS NULL AND a.date BETWEEN :a AND :b {where} {_scope_sql(a)}
    """, {"a": f["start"], "b": f["end"], **p})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    code = {"present": "P", "absent": "A", "late": "L", "excused": "E", "leave": "LV"}
    df["status"] = df["status"].map(code)
    wide = df.pivot_table(index=["admission_no", "student"], columns="date", values="status",
                          aggfunc="first", fill_value="").reset_index()
    wide.columns = [str(c)[5:] if str(c)[:2] == "20" else c for c in wide.columns]
    return wide.rename(columns={"admission_no": "Admission no", "student": "Student"})


def attendance_percent(a: Actor, f):
    df = attendance.percentages(a.tenant, f["start"], f["end"], f.get("class_id"))
    if df.empty:
        return df
    scope = a.class_scope()
    if scope is not None:
        df = df[df["class_id"].isin(scope)]
    return df[["admission_no", "student", "attended", "absent", "late", "excused", "marked", "percent"]].rename(
        columns={"admission_no": "Admission no", "student": "Student", "attended": "Attended",
                 "absent": "Absent", "late": "Late", "excused": "Excused/leave", "marked": "Days marked",
                 "percent": "Attendance %"})


def low_attendance(a: Actor, f):
    df = attendance_percent(a, f)
    if df.empty:
        return df
    return df[df["Attendance %"] < float(a.settings["attendance_threshold"])].sort_values("Attendance %")


def _invoice_frame(a: Actor, where="", params=None):
    rows = fees.invoices(a.tenant, where, params)
    cols = ["invoice_no", "student", "admission_no", "period_label", "issue_date", "due_date",
            "total", "paid", "balance", "state", "overdue_days"]
    df = pd.DataFrame(rows, columns=cols + ["id"])[cols] if rows else pd.DataFrame(columns=cols)
    return df.rename(columns={"invoice_no": "Invoice", "student": "Student", "admission_no": "Admission no",
                              "period_label": "Period", "issue_date": "Issued", "due_date": "Due",
                              "total": "Total", "paid": "Paid", "balance": "Balance", "state": "Status",
                              "overdue_days": "Days overdue"})


def outstanding_dues(a: Actor, f):
    df = _invoice_frame(a, "i.status='issued'")
    return df[df["Balance"] > fees.EPS].sort_values("Days overdue", ascending=False) if not df.empty else df


def invoice_list(a: Actor, f):
    return _invoice_frame(a, "i.issue_date BETWEEN :a AND :b", {"a": f["start"], "b": f["end"]})


def _payments(a: Actor, f, extra=""):
    rows = a.tenant.q(f"""
        SELECT p.payment_date AS "Date", p.receipt_no AS "Receipt", i.invoice_no AS "Invoice",
               st.first_name || ' ' || IFNULL(st.last_name,'') AS "Student", p.kind AS "Type",
               p.method AS "Method", p.amount AS "Amount", u.full_name AS "Recorded by", p.reason AS "Reason"
        FROM payments p JOIN invoices i ON i.id=p.invoice_id JOIN students st ON st.id=p.student_id
        LEFT JOIN users u ON u.id=p.recorded_by
        WHERE p.institution_id=:iid AND p.payment_date BETWEEN :a AND :b {extra}
        ORDER BY p.payment_date, p.id
    """, {"a": f["start"], "b": f["end"]})
    return pd.DataFrame(rows)


def daily_collection(a: Actor, f):
    df = _payments(a, f, "AND p.kind<>'credit_applied'")
    if df.empty:
        return df
    return df.groupby(["Date", "Method"], as_index=False)["Amount"].sum().sort_values("Date")


def monthly_collection(a: Actor, f):
    df = _payments(a, f, "AND p.kind<>'credit_applied'")
    if df.empty:
        return df
    df["Month"] = df["Date"].str[:7]
    return df.groupby("Month", as_index=False).agg(Collected=("Amount", "sum"), Receipts=("Receipt", "count"))


def cashier_collection(a: Actor, f):
    df = _payments(a, f, "AND p.kind<>'credit_applied'")
    if df.empty:
        return df
    return df.groupby("Recorded by", as_index=False).agg(Collected=("Amount", "sum"), Entries=("Receipt", "count"))


def reversals_refunds(a: Actor, f):
    rev = _payments(a, f, "AND p.kind='reversal'")
    ref = a.tenant.q("""
        SELECT substr(sc.created_at,1,10) AS "Date", '' AS "Receipt", '' AS "Invoice",
               st.first_name || ' ' || IFNULL(st.last_name,'') AS "Student", 'refund' AS "Type",
               sc.method AS "Method", sc.amount AS "Amount", u.full_name AS "Recorded by", sc.reason AS "Reason"
        FROM student_credits sc JOIN students st ON st.id=sc.student_id LEFT JOIN users u ON u.id=sc.created_by
        WHERE sc.institution_id=:iid AND sc.kind='refund' AND substr(sc.created_at,1,10) BETWEEN :a AND :b
    """, {"a": f["start"], "b": f["end"]})
    return pd.concat([rev, pd.DataFrame(ref)], ignore_index=True) if ref or not rev.empty else rev


def discounts_report(a: Actor, f):
    rows = a.tenant.q("""
        SELECT i.issue_date AS "Invoice date", i.invoice_no AS "Invoice",
               st.first_name || ' ' || IFNULL(st.last_name,'') AS "Student", it.item_type AS "Type",
               it.description AS "Description", -it.amount AS "Amount"
        FROM invoice_items it JOIN invoices i ON i.id=it.invoice_id JOIN students st ON st.id=i.student_id
        WHERE it.institution_id=:iid AND it.item_type IN ('discount','scholarship')
          AND i.issue_date BETWEEN :a AND :b AND i.status<>'cancelled'
        ORDER BY i.issue_date
    """, {"a": f["start"], "b": f["end"]})
    return pd.DataFrame(rows)


def ledger_report(a: Actor, f):
    if not f.get("student_id"):
        return pd.DataFrame()
    return fees.student_ledger(a.tenant, f["student_id"])


def marks_register(a: Actor, f):
    if not (f.get("exam_id") and f.get("class_id")):
        return pd.DataFrame()
    a.check_class(f["class_id"])
    from . import exams
    df = exams.class_result_sheet(a.tenant, a.settings, f["exam_id"], f["class_id"])
    return df.drop(columns=["student_id"], errors="ignore")


def performance_summary(a: Actor, f):
    if not f.get("exam_id"):
        return pd.DataFrame()
    rows = a.tenant.q(f"""
        SELECT s.name AS "Subject", c.name || IFNULL(' - ' || NULLIF(c.section,''),'') AS "Class",
               COUNT(r.id) AS "Students", ROUND(AVG(100.0*IFNULL(r.obtained_marks,0)/r.max_marks),1) AS "Average %",
               SUM(100.0*IFNULL(r.obtained_marks,0)/r.max_marks >= :p AND r.is_absent=0) AS "Passed",
               SUM(100.0*IFNULL(r.obtained_marks,0)/r.max_marks < :p OR r.is_absent=1) AS "Failed",
               MAX(100.0*r.obtained_marks/r.max_marks) AS "Highest %", m.status AS "Workflow"
        FROM results r JOIN marksheets m ON m.id=r.marksheet_id JOIN subjects s ON s.id=r.subject_id
        JOIN classes c ON c.id=m.class_id JOIN students st ON st.id=r.student_id
        WHERE r.institution_id=:iid AND m.exam_id=:e AND r.is_exempt=0 {_scope_sql(a, 'm.class_id')}
        GROUP BY m.id ORDER BY "Class", "Subject"
    """, {"e": int(f["exam_id"]), "p": float(a.settings["pass_percent"])})
    return pd.DataFrame(rows)


def staff_directory(a: Actor, f):
    rows = a.tenant.q("""
        SELECT s.staff_no AS "Staff no", s.full_name AS "Name", s.designation AS "Designation",
               d.name AS "Department", s.staff_type AS "Type", s.phone AS "Phone", s.email AS "Email",
               s.joining_date AS "Joined", s.employment_status AS "Status",
               CASE WHEN s.user_id IS NULL THEN 'No' ELSE 'Yes' END AS "Has login"
        FROM staff s LEFT JOIN departments d ON d.id=s.department_id
        WHERE s.institution_id=:iid ORDER BY s.full_name
    """)
    return pd.DataFrame(rows)


def teacher_workload(a: Actor, f):
    return people.workload(a.tenant).rename(columns={
        "staff_no": "Staff no", "full_name": "Name", "designation": "Designation",
        "assignments": "Class/subject assignments", "weekly_periods": "Weekly periods",
        "class_teacher_of": "Class teacher of"})


def staff_attendance_report(a: Actor, f):
    rows = a.tenant.q("""
        SELECT s.staff_no AS "Staff no", s.full_name AS "Name",
               SUM(sa.status='present') AS "Present", SUM(sa.status='absent') AS "Absent",
               SUM(sa.status='late') AS "Late", SUM(sa.status IN ('leave','excused')) AS "Leave"
        FROM staff s LEFT JOIN staff_attendance sa ON sa.staff_id=s.id AND sa.date BETWEEN :a AND :b
        WHERE s.institution_id=:iid GROUP BY s.id ORDER BY s.full_name
    """, {"a": f["start"], "b": f["end"]})
    return pd.DataFrame(rows)


def leave_report(a: Actor, f):
    rows = a.tenant.q("""
        SELECT s.full_name AS "Staff", l.leave_type AS "Type", l.from_date AS "From", l.to_date AS "To",
               l.days AS "Days", l.status AS "Status", l.reason AS "Reason"
        FROM leave_requests l JOIN staff s ON s.id=l.staff_id
        WHERE l.institution_id=:iid AND l.from_date <= :b AND l.to_date >= :a ORDER BY l.from_date
    """, {"a": f["start"], "b": f["end"]})
    return pd.DataFrame(rows)


def year_comparison(a: Actor, f):
    rows = a.tenant.q("""
        SELECT y.name AS "Academic year",
               (SELECT COUNT(DISTINCT e.student_id) FROM enrollments e WHERE e.academic_year_id=y.id) AS "Enrolled",
               (SELECT COUNT(*) FROM students s WHERE s.institution_id=y.institution_id
                  AND s.admission_date BETWEEN y.start_date AND y.end_date) AS "New admissions",
               (SELECT IFNULL(SUM(p.amount),0) FROM payments p WHERE p.institution_id=y.institution_id
                  AND p.kind<>'credit_applied' AND p.payment_date BETWEEN y.start_date AND y.end_date) AS "Fees collected",
               (SELECT ROUND(100.0*SUM(a.status IN ('present','late'))/NULLIF(SUM(a.status NOT IN ('excused','leave')),0),1)
                  FROM attendance a WHERE a.institution_id=y.institution_id
                  AND a.date BETWEEN y.start_date AND y.end_date) AS "Attendance %"
        FROM academic_years y WHERE y.institution_id=:iid ORDER BY y.start_date
    """)
    return pd.DataFrame(rows)


REPORTS = [
    Report("students", "Student directory", "Students", "reports.academic", ("class",), student_directory),
    Report("admissions", "Admission register", "Students", "reports.academic", ("dates",), admission_register),
    Report("status", "Student status by class", "Students", "reports.academic", (), status_report),
    Report("att_register", "Attendance register (daily)", "Attendance", "reports.academic", ("dates", "class"), attendance_register),
    Report("att_percent", "Attendance percentages", "Attendance", "reports.academic", ("dates", "class"), attendance_percent),
    Report("att_low", "Low attendance", "Attendance", "reports.academic", ("dates", "class"), low_attendance),
    Report("marks", "Marks register / class result", "Exams", "reports.academic", ("exam", "class"), marks_register),
    Report("performance", "Exam performance summary", "Exams", "reports.academic", ("exam",), performance_summary),
    Report("invoices", "Invoices", "Finance", "reports.finance", ("dates",), invoice_list),
    Report("dues", "Outstanding dues / arrears", "Finance", "reports.finance", (), outstanding_dues),
    Report("daily", "Daily collection", "Finance", "reports.finance", ("dates",), daily_collection),
    Report("monthly", "Monthly collection", "Finance", "reports.finance", ("dates",), monthly_collection),
    Report("cashier", "Cashier-wise collection", "Finance", "reports.finance", ("dates",), cashier_collection),
    Report("refunds", "Reversals and refunds", "Finance", "reports.finance", ("dates",), reversals_refunds),
    Report("discounts", "Discounts and scholarships", "Finance", "reports.finance", ("dates",), discounts_report),
    Report("ledger", "Student ledger", "Finance", "reports.finance", ("student",), ledger_report),
    Report("staff", "Staff directory", "Staff", "reports.academic", (), staff_directory),
    Report("workload", "Teacher workload", "Staff", "reports.academic", (), teacher_workload),
    Report("staff_att", "Staff attendance", "Staff", "reports.academic", ("dates",), staff_attendance_report),
    Report("leave", "Leave report", "Staff", "reports.academic", ("dates",), leave_report),
    Report("years", "Academic year comparison", "Institution", "reports.academic", (), year_comparison),
]
