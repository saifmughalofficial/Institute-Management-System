import json
from datetime import date

import pandas as pd
import streamlit as st

from ims import people, session, ui, widgets
from ims.people import APPLICATION_STATUSES, DOC_CHECKLIST, GENDERS

a = session.require("admissions.manage")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header("Admissions", "Applications, document checklist, review and enrolment")
classes = people.class_options(a, only_scope=False)
programs = widgets.lookup(a, "programs") if P["programs_enabled"] else {}

counts = {s: T.count("applications", "status=?", (s,)) for s in APPLICATION_STATUSES}
row = st.container(horizontal=True)
for s_ in APPLICATION_STATUSES:
    row.metric(s_.replace("_", " ").capitalize(), counts[s_], width="stretch")

t1, t2, t3 = st.tabs(["Applications", "New application", "Review & decide"])
with t1:
    status_f = st.pills("Status", APPLICATION_STATUSES, selection_mode="multi", default=["submitted", "under_review"])
    apps = T.all("applications", f"status IN ({','.join('?' * len(status_f))})" if status_f else "",
                 tuple(status_f), order="created_at DESC")
    if apps:
        df = pd.DataFrame(apps)
        df["applied_for"] = df["applied_class_id"].map(classes).fillna(df["applied_program_id"].map(programs))
        st.dataframe(df[["application_no", "first_name", "last_name", "applied_for", "guardian_name",
                         "guardian_phone", "status", "created_at"]], hide_index=True)
        widgets.export_buttons(a, "Admission applications", df[["application_no", "first_name", "last_name",
                                                                 "applied_for", "status", "created_at"]], "app_exp")
    else:
        widgets.empty("No applications with that status.")

with t2:
    with st.form("new_app", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        first, last = c1.text_input("First name *"), c2.text_input("Last name")
        gender = c3.selectbox("Gender", GENDERS, index=None)
        c1, c2, c3 = st.columns(3)
        dob = c1.date_input("Date of birth", value=None, min_value=date(1950, 1, 1), max_value=date.today())
        phone, email = c2.text_input("Phone"), c3.text_input("Email")
        address = st.text_input("Address")
        c1, c2, c3 = st.columns(3)
        g_name, g_phone = c1.text_input("Guardian name"), c2.text_input("Guardian phone")
        g_rel = c3.selectbox("Relationship", ["Father", "Mother", "Guardian", "Other"])
        c1, c2, c3 = st.columns(3)
        cls = c1.selectbox(f"Applying for ({P['class'].lower()})", list(classes), format_func=classes.get, index=None)
        prog = c2.selectbox(P["program"] or "Program", list(programs), format_func=programs.get, index=None) if programs else None
        prev = c3.text_input("Previous school / qualification")
        prev_res = st.text_input("Previous result / grades")
        st.markdown("**Document checklist**")
        cols = st.columns(3)
        docs = {d: cols[i % 3].checkbox(d, key=f"nd_{i}") for i, d in enumerate(DOC_CHECKLIST)}
        status = st.segmented_control("Save as", ["draft", "submitted"], default="submitted")
        if st.form_submit_button("Save application", type="primary", icon=":material/save:"):
            aid = session.attempt(people.create_application, a, {
                "first_name": first, "last_name": last, "gender": gender, "dob": dob, "phone": phone, "email": email,
                "address": address, "guardian_name": g_name, "guardian_phone": g_phone, "guardian_relationship": g_rel,
                "applied_class_id": cls, "applied_program_id": prog, "previous_school": prev,
                "previous_result": prev_res, "status": status or "submitted", "documents": docs})
            if aid:
                session.flash("Application saved.")
                st.rerun()

with t3:
    apps = T.all("applications", order="created_at DESC")
    if not apps:
        widgets.empty("No applications yet.")
    else:
        opts = {x["id"]: f"{x['application_no']} · {x['first_name']} {x['last_name'] or ''} · {x['status']}" for x in apps}
        aid = st.selectbox("Application", list(opts), format_func=opts.get)
        ap = T.require("applications", aid)
        c1, c2 = st.columns([3, 2])
        with c1, st.container(border=True):
            st.markdown(f"### {ap['first_name']} {ap['last_name'] or ''}  {ui.badge_md(ap['status'])}")
            st.table({"Field": ["Application no", "DOB", "Phone", "Guardian", "Applying for", "Previous school", "Result"],
                      "Value": [ap["application_no"], ui.fmt_date(ap["dob"], S), ap["phone"] or "—",
                                f"{ap['guardian_name'] or '—'} ({ap['guardian_phone'] or ''})",
                                classes.get(ap["applied_class_id"]) or programs.get(ap["applied_program_id"]) or "—",
                                ap["previous_school"] or "—", ap["previous_result"] or "—"]})
            docs = json.loads(ap["documents_json"] or "{}")
            st.markdown("**Documents:** " + " ".join(f":{'green' if docs.get(d) else 'gray'}-badge[{d}]" for d in DOC_CHECKLIST))
            for d in T.all("documents", "application_id=?", (aid,)):
                st.caption(f":material/attach_file: {d['doc_type']} · {d['original_name']}")
            up = st.file_uploader("Attach a document", type=["pdf", "png", "jpg", "jpeg", "webp"], max_upload_size=5,
                                  key=f"apdoc_{aid}")
            if up is not None and st.button("Upload document", icon=":material/upload:"):
                if session.attempt(people.save_document, a, up.name, up.getvalue(), "Application document",
                                   application_id=aid, success="Uploaded."):
                    st.rerun()
        with c2, st.container(border=True):
            if ap["status"] == "accepted":
                st.success("Accepted and enrolled.", icon=":material/check_circle:")
            else:
                st.markdown("**Decision**")
                new = st.selectbox("Set status", ["submitted", "under_review", "waitlisted", "rejected"])
                notes = st.text_area("Notes", ap["notes"] or "")
                if st.button("Update status", icon=":material/update:"):
                    if session.attempt(people.set_application_status, a, aid, new, notes, success="Status updated."):
                        st.rerun()
                st.divider()
                cls = st.selectbox(f"Enrol into {P['class'].lower()}", list(classes), format_func=classes.get,
                                   index=list(classes).index(ap["applied_class_id"]) if ap["applied_class_id"] in classes else None)
                if st.button("Accept & enrol", type="primary", icon=":material/how_to_reg:",
                             disabled=ap["status"] == "rejected"):
                    sid = session.attempt(people.accept_application, a, aid, cls)
                    if sid:
                        session.flash("Student enrolled. Open Students to complete the profile.")
                        st.rerun()
