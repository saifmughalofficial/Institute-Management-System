import json

import pandas as pd
import streamlit as st

from ims import exams, fees, people, session, ui
from ims import attendance as att

a = session.require("approvals.view", "results.approve", "discounts.approve", "leave.approve",
                    "students.approve_transfer")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header("Approvals", "Everything waiting for a decision in one queue")


def section(title, count):
    st.markdown(f"#### {title} " + (f":orange-badge[{count}]" if count else ":green-badge[clear]"))


# Results workflow
if a.can("results.review", "results.approve", "results.publish"):
    rows = T.q("""SELECT m.id, m.status, e.name AS exam, s.name AS subject,
                  c.name || IFNULL(' – ' || NULLIF(c.section,''),'') AS cls, u.full_name AS submitted_by, m.submitted_at
                  FROM marksheets m JOIN exams e ON e.id=m.exam_id JOIN subjects s ON s.id=m.subject_id
                  JOIN classes c ON c.id=m.class_id LEFT JOIN users u ON u.id=m.submitted_by
                  WHERE m.institution_id=:iid AND m.status IN ('submitted','reviewed','approved') ORDER BY m.submitted_at""")
    actionable = [r for r in rows if (r["status"] == "submitted" and a.can("results.review")) or
                  (r["status"] == "reviewed" and a.can("results.approve")) or
                  (r["status"] == "approved" and a.can("results.publish"))]
    section("Result marksheets", len(actionable))
    for r in actionable:
        with st.container(border=True):
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            c1.markdown(f"{ui.badge_md(r['status'])} **{r['exam']}** · {r['subject']} · {r['cls']}  \n"
                        f"Submitted by {r['submitted_by'] or '—'} · {ui.fmt_date(r['submitted_at'], S)}")
            act = {"submitted": ("review", "Mark reviewed"), "reviewed": ("approve", "Approve"),
                   "approved": ("publish", "Publish")}[r["status"]]
            b = c2.container(horizontal=True)
            if b.button(act[1], key=f"ms_{r['id']}", type="primary", icon=":material/check:"):
                if session.attempt(exams.transition, a, r["id"], act[0], success=f"Marksheet {act[0]}ed."):
                    st.rerun()
            with c2.popover("Return", icon=":material/undo:"):
                reason = st.text_input("Reason", key=f"rr_{r['id']}")
                if st.button("Return to teacher", key=f"rb_{r['id']}"):
                    if session.attempt(exams.transition, a, r["id"], "return", reason, success="Returned."):
                        st.rerun()
            with c2.popover("Preview marks", icon=":material/visibility:"):
                ms = T.get("marksheets", r["id"])
                st.dataframe(exams.marksheet_frame(a, ms).drop(columns=["student_id"]), hide_index=True)

# Discounts
if a.can("discounts.approve"):
    reqs = T.q("""SELECT d.*, i.invoice_no, st.first_name || ' ' || IFNULL(st.last_name,'') AS student, u.full_name AS by_user
                  FROM discount_requests d JOIN invoices i ON i.id=d.invoice_id JOIN students st ON st.id=i.student_id
                  LEFT JOIN users u ON u.id=d.requested_by WHERE d.institution_id=:iid AND d.status='pending'""")
    section("Fee discount requests", len(reqs))
    for r in reqs:
        inv = fees.invoice(T, r["invoice_id"])
        with st.container(border=True):
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            c1.markdown(f"**{ui.money(r['amount'], S)}** off {r['invoice_no']} · {r['student']}  \n"
                        f"{r['reason']} · requested by {r['by_user']} · "
                        f"{r['amount'] / inv['gross'] * 100 if inv['gross'] else 0:.0f}% of fees")
            b = c2.container(horizontal=True)
            if b.button("Approve", key=f"da_{r['id']}", type="primary", icon=":material/check:"):
                if session.attempt(fees.decide_discount, a, r["id"], True, success="Discount approved."):
                    st.rerun()
            if b.button("Reject", key=f"dr_{r['id']}", icon=":material/close:"):
                if session.attempt(fees.decide_discount, a, r["id"], False, success="Discount rejected."):
                    st.rerun()

# Leave
if a.can("leave.approve"):
    lv = T.q("""SELECT l.*, s.full_name FROM leave_requests l JOIN staff s ON s.id=l.staff_id
                WHERE l.institution_id=:iid AND l.status='pending' ORDER BY l.from_date""")
    section("Leave requests", len(lv))
    for r in lv:
        with st.container(border=True):
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            bal = att.leave_balance(T, r["staff_id"], S).get(r["leave_type"], {})
            c1.markdown(f"**{r['full_name']}** · {r['leave_type']} · {r['days']:g} day(s) · "
                        f"{ui.fmt_date(r['from_date'], S)} → {ui.fmt_date(r['to_date'], S)}  \n"
                        f"{r['reason'] or ''} · balance left: {bal.get('left', '—')}")
            b = c2.container(horizontal=True)
            if b.button("Approve", key=f"la_{r['id']}", type="primary", icon=":material/check:"):
                if session.attempt(att.decide_leave, a, r["id"], True, success="Leave approved."):
                    st.rerun()
            if b.button("Reject", key=f"lr_{r['id']}", icon=":material/close:"):
                if session.attempt(att.decide_leave, a, r["id"], False, success="Leave rejected."):
                    st.rerun()

# Transfers / withdrawals
if a.can("students.approve_transfer"):
    crs = T.q("""SELECT r.*, st.first_name || ' ' || IFNULL(st.last_name,'') AS student, st.admission_no, u.full_name AS by_user
                 FROM change_requests r JOIN students st ON st.id=r.student_id LEFT JOIN users u ON u.id=r.requested_by
                 WHERE r.institution_id=:iid AND r.status='pending'""")
    section("Student transfers & withdrawals", len(crs))
    for r in crs:
        with st.container(border=True):
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            c1.markdown(f"**{r['student']}** ({r['admission_no']}) → **{json.loads(r['payload_json'])['status']}**  \n"
                        f"{r['reason']} · requested by {r['by_user']}")
            b = c2.container(horizontal=True)
            if b.button("Approve", key=f"ca_{r['id']}", type="primary", icon=":material/check:"):
                if session.attempt(people.decide_change_request, a, r["id"], True, success="Approved."):
                    st.rerun()
            if b.button("Reject", key=f"cr_{r['id']}", icon=":material/close:"):
                if session.attempt(people.decide_change_request, a, r["id"], False, success="Rejected."):
                    st.rerun()

# Admissions
if a.can("admissions.manage"):
    apps = T.all("applications", "status IN ('submitted','under_review')", order="created_at")
    section("Admission applications", len(apps))
    if apps:
        st.dataframe(pd.DataFrame(apps)[["application_no", "first_name", "last_name", "status", "created_at"]],
                     hide_index=True)
        st.page_link("app_pages/admissions.py", label="Open admissions", icon=":material/arrow_forward:")
