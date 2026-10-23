from datetime import date

import pandas as pd
import streamlit as st

from ims import attendance as att, db, people, reports, session, ui, widgets
from ims.people import EMPLOYMENT_STATUSES, GENDERS

a = session.require("staff.view", "staff.manage", "staff_attendance.manage", "leave.approve")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header(P["staff_plural"].capitalize(), "Profiles, assignments, attendance, leave and workload")
depts = widgets.lookup(a, "departments")

names = []
if a.can("staff.view", "staff.manage"):
    names += ["Directory", "Profile"]
if a.can("staff.manage"):
    names.append("Add staff")
if a.can("staff_attendance.manage"):
    names.append("Staff attendance")
if a.can("leave.approve"):
    names.append("Leave")
names.append("Workload")
tabs = dict(zip(names, st.tabs(names)))

if "Directory" in tabs:
    with tabs["Directory"]:
        df = reports.staff_directory(a, {})
        st.dataframe(df, hide_index=True)
        widgets.export_buttons(a, "Staff directory", df, "staff_exp")

if "Add staff" in tabs:
    with tabs["Add staff"], st.form("add_staff", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Full name *")
        no = c2.text_input("Staff no", placeholder="Auto if blank")
        desig = c3.text_input("Designation", "Teacher" if P["short"] == "School" else "Lecturer")
        c1, c2, c3 = st.columns(3)
        gender = c1.selectbox("Gender", GENDERS, index=None)
        stype = c2.selectbox("Type", ["teaching", "non-teaching", "research"])
        dept = c3.selectbox("Department", list(depts), format_func=depts.get, index=None) if depts else None
        c1, c2, c3 = st.columns(3)
        phone, email = c1.text_input("Phone"), c2.text_input("Email")
        joined = c3.date_input("Joining date", date.today())
        qual = st.text_input("Qualifications")
        if st.form_submit_button("Save", type="primary", icon=":material/person_add:"):
            if session.attempt(people.create_staff, a, {"full_name": name, "staff_no": no.strip() or None,
                               "designation": desig, "gender": gender, "staff_type": stype, "department_id": dept,
                               "phone": phone, "email": email, "joining_date": joined, "qualifications": qual},
                               success="Staff member added."):
                st.rerun()

if "Profile" in tabs:
    with tabs["Profile"]:
        staff = T.all("staff", order="full_name")
        if not staff:
            widgets.empty("No staff yet.")
        else:
            opts = {s["id"]: f"{s['full_name']} · {s['staff_no']}" for s in staff}
            sid = st.selectbox("Staff member", list(opts), format_func=opts.get)
            s = T.require("staff", sid)
            c1, c2 = st.columns([3, 2])
            with c1:
                if a.can("staff.manage"):
                    with st.form("edit_staff"):
                        x1, x2 = st.columns(2)
                        name = x1.text_input("Full name", s["full_name"])
                        desig = x2.text_input("Designation", s["designation"] or "")
                        phone = x1.text_input("Phone", s["phone"] or "")
                        email = x2.text_input("Email", s["email"] or "")
                        status = x1.selectbox("Employment status", EMPLOYMENT_STATUSES,
                                              index=EMPLOYMENT_STATUSES.index(s["employment_status"]))
                        dept = x2.selectbox("Department", [None] + list(depts),
                                            format_func=lambda k: "—" if k is None else depts[k],
                                            index=([None] + list(depts)).index(s["department_id"]) if s["department_id"] in depts else 0)
                        qual = st.text_input("Qualifications", s["qualifications"] or "")
                        if st.form_submit_button("Save changes", type="primary", icon=":material/save:"):
                            if session.attempt(people.update_staff, a, sid, {"full_name": name, "designation": desig,
                                               "phone": phone, "email": email, "employment_status": status,
                                               "department_id": dept, "qualifications": qual}, success="Saved."):
                                st.rerun()
                else:
                    st.table({"Field": ["Designation", "Phone", "Email", "Status"],
                              "Value": [s["designation"], s["phone"], s["email"], s["employment_status"]]})
            with c2, st.container(border=True):
                st.markdown("**Assignments**")
                asg = T.q("""SELECT c.name || IFNULL(' – ' || NULLIF(c.section,''),'') AS cls, IFNULL(sub.name,'Whole class') AS subject
                             FROM teacher_assignments t JOIN classes c ON c.id=t.class_id LEFT JOIN subjects sub ON sub.id=t.subject_id
                             WHERE t.institution_id=:iid AND t.staff_id=:s""", {"s": sid})
                st.dataframe(pd.DataFrame(asg), hide_index=True) if asg else st.caption("No assignments.")
                st.markdown("**Login:** " + ("linked" if s["user_id"] else "none (create one in Users & roles)"))
                bal = att.leave_balance(T, sid, S)
                st.markdown("**Leave balance:** " + " · ".join(f"{k} {v['left']:g}/{v['allowed']}" for k, v in bal.items()))
                if a.can("staff.manage"):
                    for d in T.all("documents", "staff_id=?", (sid,)):
                        def _get(did=d["id"]):
                            return people.read_document(a, did)[0]
                        st.download_button(f"{d['doc_type']}: {d['original_name']}", _get, d["original_name"], d["mime"],
                                           key=f"sd_{d['id']}", on_click="ignore", icon=":material/download:")
                    up = st.file_uploader("Upload contract / document", type=["pdf", "png", "jpg", "jpeg", "webp"],
                                          max_upload_size=5, key=f"sdu_{sid}")
                    if up is not None and st.button("Upload", key="sdu_btn"):
                        if session.attempt(people.save_document, a, up.name, up.getvalue(), "Staff document",
                                           staff_id=sid, success="Uploaded."):
                            st.rerun()

if "Staff attendance" in tabs:
    with tabs["Staff attendance"]:
        day = st.date_input("Date", date.today(), max_value=date.today(), key="sa_day")
        staff = T.all("staff", "employment_status='active'", order="full_name")
        existing = {r["staff_id"]: r for r in T.all("staff_attendance", "date=?", (day.isoformat(),))}
        df = pd.DataFrame({"id": [s["id"] for s in staff], "Name": [s["full_name"] for s in staff],
                           "Status": [existing.get(s["id"], {}).get("status", "present") for s in staff],
                           "Remark": [existing.get(s["id"], {}).get("remark") or "" for s in staff]})
        ed = st.data_editor(df, hide_index=True, disabled=["Name"], key=f"sa_ed_{day}",
                            column_config={"id": None, "Status": st.column_config.SelectboxColumn(options=att.STATUSES, required=True)})
        if st.button("Save staff attendance", type="primary", icon=":material/save:"):
            with db.transaction():
                for r in ed.itertuples():
                    ex = existing.get(r.id)
                    if ex:
                        T.update("staff_attendance", ex["id"], status=r.Status, remark=r.Remark, marked_by=a.uid)
                    else:
                        T.insert("staff_attendance", staff_id=r.id, date=day.isoformat(), status=r.Status,
                                 remark=r.Remark, marked_by=a.uid)
                a.log("staff_attendance_saved", "staff_attendance", None, {"date": day.isoformat()})
            session.flash("Staff attendance saved.")
            st.rerun()

if "Leave" in tabs:
    with tabs["Leave"]:
        lv = T.q("""SELECT l.id, s.full_name, l.leave_type, l.from_date, l.to_date, l.days, l.status, l.reason
                    FROM leave_requests l JOIN staff s ON s.id=l.staff_id WHERE l.institution_id=:iid ORDER BY l.created_at DESC""")
        st.dataframe(pd.DataFrame(lv), hide_index=True) if lv else widgets.empty("No leave requests.")
        st.page_link("app_pages/approvals.py", label="Decide pending leave in Approvals", icon=":material/task_alt:")

with tabs["Workload"]:
    wl = reports.teacher_workload(a, {})
    st.dataframe(wl, hide_index=True, column_config={"Weekly periods": st.column_config.ProgressColumn(
        min_value=0, max_value=max(int(wl["Weekly periods"].max() or 1), 1) if not wl.empty else 1, format="%d")})
