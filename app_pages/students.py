from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ims import attendance, branding, db, exams, fees, pdf, people, session, ui, widgets
from ims.people import GENDERS, STUDENT_STATUSES, full_name

a = session.require("students.view")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header("Students", f"Profiles, guardians, documents and the full student lifecycle · {P['short']}", tips=[
    "**Directory**: search by name, admission number or phone, then click a row to select that student.",
    "**Student profile**: edit details, link guardians (siblings share one), upload documents, print the ID card or admission form.",
    "**Add student**: leave the admission number blank to generate it automatically.",
    "**Promote / transfer**: move a whole class at once. Untick anyone repeating the year.",
    "**Import CSV**: download the template, fill it in, check the preview, then import only the valid rows."])

classes = people.class_options(a)
all_classes = people.class_options(a, only_scope=False)
programs = widgets.lookup(a, "programs") if P["programs_enabled"] else {}
scope = a.class_scope()

tab_names = ["Directory", "Student profile"]
if a.can("students.manage"):
    tab_names += ["Add student", "Promote / transfer"]
if a.can("students.import"):
    tab_names.append("Import CSV")
tabs = dict(zip(tab_names, st.tabs(tab_names)))

# ------------------------------------------------------------------ directory
with tabs["Directory"]:
    f = st.container(horizontal=True, vertical_alignment="bottom")
    search = f.text_input("Search", placeholder="Name, admission no, phone…", width=300)
    cls_f = f.selectbox(P["class"], [None] + list(classes), format_func=lambda k: "All" if k is None else classes[k],
                        width=220)
    status_f = f.multiselect("Status", STUDENT_STATUSES, default=["active"], width=320)
    where, params = ["st.institution_id=:iid"], {}
    if status_f:
        where.append("st.status IN (" + ",".join(f"'{s}'" for s in status_f if s in STUDENT_STATUSES) + ")")
    if cls_f:
        where.append("st.class_id=:c")
        params["c"] = cls_f
    if scope is not None:
        where.append(f"st.class_id IN ({','.join(map(str, scope)) or '0'})")
    if search.strip():
        where.append("(st.first_name || ' ' || IFNULL(st.last_name,'') LIKE :q OR st.admission_no LIKE :q OR st.phone LIKE :q)")
        params["q"] = f"%{search.strip()}%"
    rows = T.q(f"""SELECT st.id, st.admission_no, st.first_name || ' ' || IFNULL(st.last_name,'') AS name, st.gender,
                   c.name || IFNULL(' – ' || NULLIF(c.section,''),'') AS class, st.phone, st.status, st.admission_date
                   FROM students st LEFT JOIN classes c ON c.id=st.class_id WHERE {' AND '.join(where)}
                   ORDER BY c.name, c.section, st.first_name""", params)
    df = pd.DataFrame(rows, columns=["id", "admission_no", "name", "gender", "class", "phone", "status", "admission_date"])
    st.caption(f"{len(df)} student(s)")
    event = st.dataframe(df.drop(columns="id"), hide_index=True, on_select="rerun", selection_mode="single-row",
                         key="dir_table", column_config={
                             "admission_no": "Admission no", "name": "Student", "gender": "Gender",
                             "class": P["class"], "phone": "Phone", "status": "Status",
                             "admission_date": st.column_config.DateColumn("Admitted")})
    if event.selection.rows:
        st.session_state["student_pick"] = int(df.iloc[event.selection.rows[0]]["id"])
        st.info("Student selected. Open the **Student profile** tab to see the full record.", icon=":material/person_search:")
    widgets.export_buttons(a, "Student directory", df.drop(columns="id"), "dir_exp")

# ------------------------------------------------------------------ add
if "Add student" in tabs:
    with tabs["Add student"]:
        with st.form("add_student", clear_on_submit=True):
            st.markdown("**Student details**")
            c1, c2, c3 = st.columns(3)
            first = c1.text_input("First name *")
            last = c2.text_input("Last name")
            adm = c3.text_input("Admission no", placeholder="Auto-generated if blank")
            c1, c2, c3 = st.columns(3)
            gender = c1.selectbox("Gender", GENDERS, index=None)
            dob = c2.date_input("Date of birth", value=None, min_value=date(1950, 1, 1), max_value=date.today())
            cls = c3.selectbox(P["class"], list(all_classes), format_func=all_classes.get, index=None)
            c1, c2, c3 = st.columns(3)
            phone = c1.text_input("Phone")
            email = c2.text_input("Email")
            category = c3.selectbox("Category", ["General", "Scholarship", "Staff child", "Sibling", "Other"])
            address = st.text_input("Address")
            c1, c2, c3 = st.columns(3)
            emergency = c1.text_input("Emergency contact")
            blood = c2.selectbox("Blood group", ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"])
            prev = c3.text_input("Previous school / qualification")
            st.markdown("**Guardian**" + (" *(recommended)*" if P["guardians_emphasis"] else " *(optional)*"))
            c1, c2, c3 = st.columns(3)
            g_name = c1.text_input("Guardian name")
            g_phone = c2.text_input("Guardian phone")
            g_rel = c3.selectbox("Relationship", ["Father", "Mother", "Guardian", "Sibling", "Other"])
            if st.form_submit_button("Save student", type="primary", icon=":material/person_add:"):
                c = T.get("classes", cls) if cls else None
                sid = session.attempt(people.create_student, a, {
                    "first_name": first, "last_name": last, "admission_no": adm.strip() or None, "gender": gender,
                    "dob": dob, "class_id": cls, "program_id": (c or {}).get("program_id"),
                    "academic_year_id": (c or {}).get("academic_year_id"), "phone": phone, "email": email,
                    "category": category, "address": address, "emergency_contact": emergency,
                    "blood_group": blood, "previous_school": prev},
                    guardian={"name": g_name, "phone": g_phone, "relationship": g_rel})
                if sid:
                    st.session_state["student_pick"] = sid
                    session.flash(f"{first} {last} was added.")
                    st.rerun()

# ------------------------------------------------------------------ profile
with tabs["Student profile"]:
    opts = widgets.student_options(a, statuses=None)
    if not opts:
        widgets.empty("No students yet.")
    else:
        keys = list(opts)
        pick = st.session_state.get("student_pick")
        sid = st.selectbox("Student", keys, format_func=opts.get, index=keys.index(pick) if pick in keys else 0,
                           key="profile_select")
        st.session_state["student_pick"] = sid
        s = T.require("students", sid)
        cls = T.get("classes", s["class_id"])
        photo = branding.read_file(a.iid, s["photo_path"])
        top = st.container(border=True)
        c1, c2, c3 = top.columns([1, 3, 2], vertical_alignment="center")
        c1.image(photo or branding.monogram_png(full_name(s), S["accent"]), width=110)
        c2.markdown(f"### {full_name(s)}")
        c2.markdown(f"{ui.badge_md(s['status'])} &nbsp; `{s['admission_no']}` &nbsp; {P['class']}: **{people.class_label(cls)}**"
                    + (f" &nbsp; {P['program']}: **{programs.get(s['program_id'], '—')}**" if programs else ""))
        sibs = people.siblings(T, sid)
        if sibs:
            c2.caption("Siblings: " + ", ".join(f"{full_name(x)} ({x['admission_no']})" for x in sibs))
        guardians = T.q("SELECT g.*, sg.relationship, sg.is_primary FROM student_guardians sg JOIN guardians g "
                        "ON g.id=sg.guardian_id WHERE sg.institution_id=:iid AND sg.student_id=:s ORDER BY sg.is_primary DESC",
                        {"s": sid})
        with c3:
            st.download_button("ID card", lambda: pdf.id_card_pdf(a.inst, S, s, people.class_label(cls), photo),
                               f"ID_{s['admission_no']}.pdf", "application/pdf", icon=":material/badge:",
                               on_click="ignore", width="stretch")
            st.download_button("Admission form", lambda: pdf.admission_form_pdf(a.inst, S, s, guardians,
                                                                               people.class_label(cls), photo),
                               f"Admission_{s['admission_no']}.pdf", "application/pdf", icon=":material/description:",
                               on_click="ignore", width="stretch")

        sub = ["Details", "Guardians", "Attendance", "Results", "History"]
        if a.can("fees.view"):
            sub.insert(3, "Fees")
        if a.can("students.documents"):
            sub.append("Documents")
        if a.can("students.manage", "students.approve_transfer"):
            sub.append("Status")
        st_tabs = dict(zip(sub, st.tabs(sub)))

        with st_tabs["Details"]:
            if a.can("students.manage"):
                with st.form("edit_student"):
                    c1, c2, c3 = st.columns(3)
                    first = c1.text_input("First name", s["first_name"])
                    last = c2.text_input("Last name", s["last_name"] or "")
                    adm = c3.text_input("Admission no", s["admission_no"])
                    c1, c2, c3 = st.columns(3)
                    gender = c1.selectbox("Gender", GENDERS, index=GENDERS.index(s["gender"]) if s["gender"] in GENDERS else None)
                    dob = c2.date_input("Date of birth", value=date.fromisoformat(s["dob"]) if s["dob"] else None,
                                        min_value=date(1950, 1, 1), max_value=date.today())
                    category = c3.text_input("Category", s["category"] or "")
                    c1, c2, c3 = st.columns(3)
                    phone = c1.text_input("Phone", s["phone"] or "")
                    email = c2.text_input("Email", s["email"] or "")
                    emergency = c3.text_input("Emergency contact", s["emergency_contact"] or "")
                    address = st.text_input("Address", s["address"] or "")
                    c1, c2, c3 = st.columns(3)
                    blood = c1.text_input("Blood group", s["blood_group"] or "")
                    nid = c2.text_input("National ID / B-form", s["national_id"] or "")
                    prev = c3.text_input("Previous school", s["previous_school"] or "")
                    up = st.file_uploader("Photo (PNG/JPG/WebP, max 2 MB)", type=["png", "jpg", "jpeg", "webp"],
                                          max_upload_size=2)
                    if st.form_submit_button("Save changes", type="primary", icon=":material/save:"):
                        data = {"first_name": first, "last_name": last, "admission_no": adm.strip(), "gender": gender,
                                "dob": dob, "category": category, "phone": phone, "email": email,
                                "emergency_contact": emergency, "address": address, "blood_group": blood,
                                "national_id": nid, "previous_school": prev}
                        ok = True
                        if up is not None:
                            try:
                                png = branding.validate_image(up.name, up.getvalue(), branding.MAX_LOGO_BYTES, 600)
                                data["photo_path"] = branding.save_file(a.iid, "photos", png, "png")
                            except branding.UploadError as exc:
                                st.error(str(exc))
                                ok = False
                        if ok and session.attempt(people.update_student, a, sid, data, success="Student updated."):
                            st.rerun()
            else:
                st.table({"Field": ["Gender", "Date of birth", "Phone", "Email", "Address", "Admitted", "Category"],
                          "Value": [s["gender"] or "—", ui.fmt_date(s["dob"], S), s["phone"] or "—", s["email"] or "—",
                                    s["address"] or "—", ui.fmt_date(s["admission_date"], S), s["category"] or "—"]})

        with st_tabs["Guardians"]:
            if guardians:
                st.dataframe(pd.DataFrame(guardians)[["name", "relationship", "phone", "email", "occupation", "is_primary"]],
                             hide_index=True, column_config={"is_primary": st.column_config.CheckboxColumn("Primary")})
            else:
                st.caption("No guardian linked.")
            if a.can("students.manage"):
                with st.expander("Link a guardian", icon=":material/family_restroom:"):
                    mode = st.segmented_control("Guardian", ["New guardian", "Existing guardian (sibling)"],
                                                default="New guardian", key="g_mode")
                    with st.form("link_guardian", clear_on_submit=True):
                        if mode == "Existing guardian (sibling)":
                            gopts = {g["id"]: f"{g['name']} · {g['phone'] or ''}" for g in T.all("guardians", order="name")}
                            gid = st.selectbox("Guardian", list(gopts), format_func=gopts.get, index=None)
                            g = {"id": gid}
                        else:
                            c1, c2 = st.columns(2)
                            g = {"name": c1.text_input("Name"), "phone": c2.text_input("Phone"),
                                 "email": c1.text_input("Email"), "occupation": c2.text_input("Occupation")}
                        rel = st.selectbox("Relationship", ["Father", "Mother", "Guardian", "Sibling", "Other"])
                        primary = st.checkbox("Primary contact")
                        if st.form_submit_button("Link guardian", icon=":material/link:"):
                            g.update(relationship=rel, is_primary=primary)
                            if g.get("id") or g.get("name"):
                                if session.attempt(people.link_guardian, a, sid, g, success="Guardian linked."):
                                    st.rerun()

        with st_tabs["Attendance"]:
            start = st.date_input("From", date.today() - timedelta(days=60), key="att_from")
            pct = attendance.percentages(T, start.isoformat(), date.today().isoformat(), student_ids=[sid])
            if not pct.empty and pd.notna(pct.iloc[0]["percent"]):
                r = pct.iloc[0]
                ui.progress(float(r["percent"]), "Attendance")
                st.caption(f"Attended {int(r['attended'])} · absent {int(r['absent'])} · late {int(r['late'])} · "
                           f"excused/leave {int(r['excused'])}")
            recs = T.all("attendance", "student_id=? AND date>=?", (sid, start.isoformat()), order="date DESC")
            if recs:
                st.dataframe(pd.DataFrame(recs)[["date", "status", "remark"]], hide_index=True, height=260)

        if "Fees" in st_tabs:
            with st_tabs["Fees"]:
                invs = fees.invoices(T, "i.student_id=:s", {"s": sid})
                credit = fees.credit_balance(T, sid)
                c1, c2, c3 = st.columns(3)
                c1.metric("Total billed", ui.money(sum(i["total"] for i in invs if i["state"] != "cancelled"), S))
                c2.metric("Balance due", ui.money(sum(i["balance"] for i in invs if i["state"] != "cancelled"), S))
                c3.metric("Advance credit", ui.money(credit, S))
                st.dataframe(fees.student_ledger(T, sid), hide_index=True)

        with st_tabs["Results"]:
            terms = T.all("terms", order="start_date DESC")
            if terms:
                tid = st.selectbox(P["term"], [t["id"] for t in terms], format_func=lambda i: T.get("terms", i)["name"],
                                   key="res_term")
                rep = exams.term_report(T, S, sid, tid, published_only=not a.can("exams.manage", "results.review"))
                if rep["lines"]:
                    st.dataframe(pd.DataFrame(rep["lines"])[["subject", "obtained", "max", "percent", "grade"]],
                                 hide_index=True)
                    st.markdown(f"**Result:** {rep['result']}" + (f" · **GPA:** {rep['gpa']:.2f}" if P["gpa"] and rep["gpa"] is not None else ""))
                else:
                    st.caption("No results for this term.")

        with st_tabs["History"]:
            hist = T.q("SELECT h.created_at, h.event, h.from_value, h.to_value, h.reason, u.full_name AS by_user "
                       "FROM student_history h LEFT JOIN users u ON u.id=h.created_by WHERE h.institution_id=:iid "
                       "AND h.student_id=:s ORDER BY h.created_at DESC", {"s": sid})
            st.dataframe(pd.DataFrame(hist), hide_index=True) if hist else st.caption("No history yet.")

        if "Documents" in st_tabs:
            with st_tabs["Documents"]:
                docs = T.all("documents", "student_id=?", (sid,), order="uploaded_at DESC")
                for d in docs:
                    c1, c2 = st.columns([4, 1], vertical_alignment="center")
                    c1.markdown(f":material/description: **{d['doc_type']}** · {d['original_name']} · "
                                f"{(d['size'] or 0) // 1024} KB · {ui.fmt_date(d['uploaded_at'], S)}")

                    def _doc(did=d["id"]):
                        data, _ = people.read_document(a, did)
                        a.log("document_downloaded", "document", did)
                        return data
                    c2.download_button("Download", _doc, d["original_name"] or "document", d["mime"],
                                       key=f"doc_{d['id']}", on_click="ignore", icon=":material/download:")
                with st.form("upload_doc", clear_on_submit=True):
                    c1, c2 = st.columns([1, 2])
                    dtype = c1.selectbox("Document type", people.DOC_CHECKLIST + ["Other"])
                    up = c2.file_uploader("File (PDF/PNG/JPG/WebP, max 5 MB)", type=["pdf", "png", "jpg", "jpeg", "webp"],
                                          max_upload_size=5)
                    if st.form_submit_button("Upload", icon=":material/upload:") and up is not None:
                        if session.attempt(people.save_document, a, up.name, up.getvalue(), dtype, student_id=sid,
                                           success="Document uploaded."):
                            st.rerun()

        if "Status" in st_tabs:
            with st_tabs["Status"]:
                st.caption("Transfers and withdrawals go to the principal for approval unless you can approve them.")
                with st.form("status_form"):
                    c1, c2 = st.columns([1, 2])
                    new = c1.selectbox("New status", [x for x in STUDENT_STATUSES if x != s["status"]])
                    reason = c2.text_input("Reason *")
                    if st.form_submit_button("Change status", icon=":material/swap_horiz:"):
                        res = session.attempt(people.change_status, a, sid, new, reason)
                        if res:
                            session.flash("Status changed." if res == "applied" else "Request sent for approval.")
                            st.rerun()

# ------------------------------------------------------------------ promote
if "Promote / transfer" in tabs:
    with tabs["Promote / transfer"]:
        st.caption("Promote a class, move students to another section, or progress a cohort to the next semester. "
                   "Untick students who repeat the year.")
        c1, c2, c3 = st.columns(3)
        src = c1.selectbox(f"From {P['class'].lower()}", list(all_classes), format_func=all_classes.get, key="pr_src")
        dst = c2.selectbox(f"To {P['class'].lower()}", list(all_classes), format_func=all_classes.get, key="pr_dst")
        event = c3.selectbox("Type", ["promotion", "section_transfer", "progression"],
                             format_func=lambda x: x.replace("_", " ").capitalize())
        if src:
            studs = T.all("students", "class_id=? AND status='active'", (src,), order="first_name")
            if studs:
                pick_df = pd.DataFrame({"Move": True, "id": [x["id"] for x in studs],
                                        "Student": [full_name(x) for x in studs],
                                        "Admission no": [x["admission_no"] for x in studs]})
                edited = st.data_editor(pick_df, hide_index=True, disabled=["Student", "Admission no"],
                                        column_config={"id": None}, key="pr_editor")
                reason = st.text_input("Note (optional)", key="pr_reason")
                chosen = edited[edited["Move"]]["id"].astype(int).tolist()
                if st.button(f"Move {len(chosen)} student(s)", type="primary", disabled=not chosen or src == dst,
                             icon=":material/trending_up:"):
                    n = session.attempt(people.move_students, a, chosen, dst, event, reason)
                    if n:
                        session.flash(f"{n} student(s) moved to {all_classes[dst]}.")
                        st.rerun()
            else:
                st.caption("No active students in that class.")

# ------------------------------------------------------------------ import
if "Import CSV" in tabs:
    with tabs["Import CSV"]:
        st.markdown("1. Download the template · 2. Fill it in · 3. Upload and check the preview · 4. Import the valid rows")
        st.download_button("Download CSV template", people.import_template(), "student_import_template.csv",
                           "text/csv", icon=":material/download:", on_click="ignore")
        up = st.file_uploader("Upload CSV", type=["csv"], max_upload_size=5, key="imp_up")
        if up is not None:
            try:
                prev = people.preview_import(a, up.getvalue())
            except Exception as exc:
                st.error(str(exc))
                prev = None
            if prev is not None:
                bad = prev[prev["errors"] != ""]
                good = len(prev) - len(bad)
                c1, c2, c3 = st.columns(3)
                c1.metric("Rows", len(prev))
                c2.metric("Valid", good)
                c3.metric("With errors", len(bad))
                st.dataframe(prev.drop(columns=["class_id"]), hide_index=True,
                             column_config={"errors": st.column_config.TextColumn("Errors", width="large")})
                if len(bad):
                    st.download_button("Download error report", bad.to_csv(index=False).encode("utf-8-sig"),
                                       "import_errors.csv", "text/csv", icon=":material/report:", on_click="ignore")
                if st.button(f"Import {good} valid row(s)", type="primary", disabled=good == 0,
                             icon=":material/upload:"):
                    n = session.attempt(people.commit_import, a, prev)
                    if n:
                        session.flash(f"Imported {n} student(s).")
                        st.rerun()
