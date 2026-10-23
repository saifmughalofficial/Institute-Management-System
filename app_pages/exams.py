import pandas as pd
import streamlit as st

from ims import academics, attendance as att, exams, pdf, people, session, ui, widgets
from ims.exams import EXAM_TYPES, WORKFLOW

a = session.require("exams.view", "marks.enter", "exams.manage", "results.review")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header("Exams & results", "Exams, marks entry, approval workflow, " + P["result_doc"].lower() + "s and corrections", tips=[
    "**Exams**: create an exam inside a term and give it a weight (e.g. midterm 40%, final 60%).",
    "**Marks entry**: choose the exam, class and subject, type the marks, then **Save & submit for review**.",
    "Reviewers and the principal approve in **Approvals**. Students and parents only see **published** results.",
    "**Results**: class result sheet with positions, or download a student's report card or transcript as a PDF."])
st.caption("Workflow: " + " → ".join(f"{ui.badge_md(w)}" for w in WORKFLOW))

names = ["Exams"]
if a.can("marks.enter", "exams.manage"):
    names.append("Marks entry")
names += ["Workflow status", "Results & " + P["result_doc"].lower() + "s"]
if a.can("results.correct"):
    names.append("Corrections")
tabs = dict(zip(names, st.tabs(names)))

with tabs["Exams"]:
    rows = T.q("""SELECT e.*, t.name AS term FROM exams e JOIN terms t ON t.id=e.term_id
                  WHERE e.institution_id=:iid ORDER BY t.start_date DESC, e.start_date""")
    if rows:
        st.dataframe(pd.DataFrame(rows)[["term", "name", "exam_type", "weightage", "start_date", "end_date", "status"]],
                     hide_index=True, column_config={"weightage": st.column_config.NumberColumn("Weight %")})
    else:
        widgets.empty("No exams yet.")
    if a.can("exams.manage"):
        terms = T.all("terms", order="start_date DESC")
        if terms:
            with st.form("add_exam", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                tid = c1.selectbox(P["term"], [t["id"] for t in terms], format_func=lambda i: academics.term_label(T, T.get("terms", i)))
                name = c2.text_input("Exam name", "Final examination")
                typ = c3.selectbox("Type", EXAM_TYPES, index=3)
                w = c4.number_input("Weight %", 1.0, 100.0, 100.0, 5.0)
                c1, c2 = st.columns(2)
                sd, ed = c1.date_input("Start", value=None), c2.date_input("End", value=None)
                if st.form_submit_button("Create exam", type="primary", icon=":material/add:") and name.strip():
                    if sd and ed and ed < sd:
                        st.error("End date is before start date.")
                    else:
                        T.insert("exams", term_id=tid, name=name.strip(), exam_type=typ, weightage=w,
                                 start_date=sd.isoformat() if sd else None, end_date=ed.isoformat() if ed else None)
                        a.log("exam_created", "exam")
                        session.flash("Exam created.")
                        st.rerun()
            st.caption("Weights combine exams within a term (e.g. midterm 40% + final 60%). A supplementary exam "
                       "replaces a subject's result when it is higher.")

if "Marks entry" in tabs:
    with tabs["Marks entry"]:
        c1, c2, c3 = st.columns(3)
        with c1:
            ex = widgets.pick_exam(a, "me_exam")
        with c2:
            cid = widgets.pick_class(a, "me_cls")
        sid = None
        if cid:
            subs = {s["id"]: s["name"] for s in academics.subjects_for_class(T, T.get("classes", cid))}
            scope = a.subject_scope(cid)
            if scope is not None:
                subs = {k: v for k, v in subs.items() if k in scope}
            sid = c3.selectbox(P["subject"], list(subs), format_func=subs.get, index=None)
        if ex and cid and sid:
            ms = session.attempt(exams.get_or_create_marksheet, a, ex["id"], cid, sid)
            if ms and ms is not True:
                st.markdown(f"Status: {ui.badge_md(ms['status'])} · max marks **{ms['max_marks']:g}**")
                if ms["return_reason"]:
                    st.warning(f"Returned: {ms['return_reason']}", icon=":material/undo:")
                df = exams.marksheet_frame(a, ms)
                locked = ms["status"] != "draft"
                if df.empty:
                    widgets.empty("No active students in this class.")
                else:
                    ed = st.data_editor(df, hide_index=True, disabled=locked or ["Admission no", "Student", "Grade"],
                                        key=f"ms_{ms['id']}_{ms['status']}", height=min(38 * len(df) + 40, 600),
                                        column_config={"student_id": None, "Marks": st.column_config.NumberColumn(
                                            min_value=0.0, max_value=float(ms["max_marks"]), step=0.5)})
                    filled = ed["Marks"].notna() | ed["Absent"] | ed["Exempt"]
                    st.caption(f"{int(filled.sum())}/{len(ed)} entered · class average "
                               f"{ed['Marks'].mean():.1f}" if ed["Marks"].notna().any() else f"{int(filled.sum())}/{len(ed)} entered")
                    if not locked:
                        b = st.container(horizontal=True)
                        entries = [{"student_id": r.student_id, "marks": r.Marks, "absent": r.Absent, "exempt": r.Exempt,
                                    "remarks": r.Remarks, "name": r.Student} for r in ed.itertuples()]
                        if b.button("Save draft", icon=":material/save:"):
                            if session.attempt(exams.save_marks, a, ms["id"], entries, success="Marks saved."):
                                st.rerun()
                        if b.button("Save & submit for review", type="primary", icon=":material/send:"):
                            if session.attempt(exams.save_marks, a, ms["id"], entries) and \
                                    session.attempt(exams.transition, a, ms["id"], "submit", success="Submitted for review."):
                                st.rerun()
                    else:
                        st.info("This marksheet is locked. Reviewers can return it; approved results use the correction workflow.",
                                icon=":material/lock:")

with tabs["Workflow status"]:
    ex = widgets.pick_exam(a, "wf_exam")
    if ex:
        rows = T.q("""SELECT m.id, c.name || IFNULL(' – ' || NULLIF(c.section,''),'') AS cls, s.name AS subject, m.status,
                      m.class_id, u.full_name AS submitted_by FROM marksheets m JOIN classes c ON c.id=m.class_id
                      JOIN subjects s ON s.id=m.subject_id LEFT JOIN users u ON u.id=m.submitted_by
                      WHERE m.institution_id=:iid AND m.exam_id=:e ORDER BY c.name, s.name""", {"e": ex["id"]})
        scope = a.class_scope()
        rows = [r for r in rows if scope is None or r["class_id"] in scope]
        if rows:
            df = pd.DataFrame(rows)
            prog = df["status"].map({w: i for i, w in enumerate(WORKFLOW)}) / (len(WORKFLOW) - 1) * 100
            st.dataframe(df.assign(progress=prog)[["cls", "subject", "status", "progress", "submitted_by"]], hide_index=True,
                         column_config={"progress": st.column_config.ProgressColumn("Progress", min_value=0, max_value=100, format="%.0f%%")})
            if a.can("results.publish"):
                ready = [r for r in rows if r["status"] == "approved"]
                if ready and st.button(f"Publish all {len(ready)} approved marksheet(s)", type="primary", icon=":material/publish:"):
                    for r in ready:
                        session.attempt(exams.transition, a, r["id"], "publish")
                    session.flash("Results published.")
                    st.rerun()
            st.page_link("app_pages/approvals.py", label="Review / approve in the Approvals queue", icon=":material/task_alt:") \
                if a.can("results.review", "results.approve") else None
        else:
            widgets.empty("No marksheets for this exam yet.")

with tabs["Results & " + P["result_doc"].lower() + "s"]:
    mode = st.segmented_control("View", ["Class result sheet", "Student " + P["result_doc"].lower()] +
                                (["Transcript"] if P["transcript"] or P["gpa"] else []), default="Class result sheet")
    if mode == "Class result sheet":
        c1, c2 = st.columns(2)
        with c1:
            ex = widgets.pick_exam(a, "rs_exam")
        with c2:
            cid = widgets.pick_class(a, "rs_cls")
        if ex and cid:
            sheet = exams.class_result_sheet(T, S, ex["id"], cid, published_only=not a.can("exams.manage", "results.review"))
            if sheet.empty:
                widgets.empty("No results yet.")
            else:
                st.dataframe(sheet.drop(columns=["student_id"]), hide_index=True,
                             column_config={"%": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f")})
                widgets.export_buttons(a, f"Result sheet {ex['name']} {people.class_label(T.get('classes', cid))}",
                                       sheet.drop(columns=["student_id"]), "rs_exp")
    elif mode and mode.startswith("Student"):
        c1, c2 = st.columns(2)
        with c1:
            term = widgets.pick_term(a, "rc_term")
        with c2:
            s = widgets.pick_student(a, "rc_student")
        if term and s:
            rep = exams.term_report(T, S, s["id"], term["id"], published_only=not a.can("exams.manage", "results.review"))
            if not rep["lines"]:
                widgets.empty("No results for this student in this term.")
            else:
                m = st.container(horizontal=True)
                m.metric("Overall %", f"{rep['percent']:.1f}" if rep["percent"] is not None else "—", width="stretch")
                if P["gpa"]:
                    m.metric("GPA", f"{rep['gpa']:.2f}" if rep["gpa"] is not None else "—", width="stretch")
                m.metric("Result", rep["result"], width="stretch")
                st.dataframe(pd.DataFrame(rep["lines"])[["subject", "code", "credit_hours", "obtained", "max", "percent", "grade", "point"]],
                             hide_index=True)
                cls = T.get("classes", s["class_id"])
                pct = att.percentages(T, term["start_date"], term["end_date"], student_ids=[s["id"]])
                ap = float(pct.iloc[0]["percent"]) if not pct.empty and pd.notna(pct.iloc[0]["percent"]) else None
                st.download_button(f"Download {P['result_doc'].lower()} (PDF)",
                                   lambda: pdf.report_card_pdf(a.inst, S, s, people.class_label(cls), term["name"], rep, ap),
                                   f"{P['result_doc']}_{s['admission_no']}.pdf", "application/pdf",
                                   icon=":material/picture_as_pdf:", on_click="ignore", type="primary")
    elif mode == "Transcript":
        s = widgets.pick_student(a, "tr_student", statuses=None)
        if s:
            tr = exams.transcript(T, S, s["id"])
            m = st.container(horizontal=True)
            m.metric("CGPA", f"{tr['cgpa']:.2f}" if tr["cgpa"] is not None else "—", width="stretch")
            m.metric("Credits earned", f"{tr['credits_earned']:g}", width="stretch")
            m.metric("Standing", tr["standing"] or "—", width="stretch")
            for t in tr["terms"]:
                with st.expander(f"{t['term']['name']} · GPA {t['report']['gpa'] or 0:.2f} · CGPA {t['cgpa'] or 0:.2f}"):
                    st.dataframe(pd.DataFrame(t["report"]["lines"])[["code", "subject", "credit_hours", "percent", "grade", "point"]],
                                 hide_index=True)
            prog = T.get("programs", s["program_id"])
            st.download_button("Download transcript (PDF)", lambda: pdf.transcript_pdf(a.inst, S, s, (prog or {}).get("name"), tr),
                               f"Transcript_{s['admission_no']}.pdf", "application/pdf", icon=":material/picture_as_pdf:",
                               on_click="ignore", type="primary")

if "Corrections" in tabs:
    with tabs["Corrections"]:
        st.caption("Change approved or published marks. A reason is required and every change is recorded.")
        c1, c2, c3 = st.columns(3)
        with c1:
            ex = widgets.pick_exam(a, "co_exam")
        with c2:
            s = widgets.pick_student(a, "co_student")
        if ex and s:
            res = T.q("""SELECT r.*, sub.name AS subject, m.status FROM results r JOIN subjects sub ON sub.id=r.subject_id
                         JOIN marksheets m ON m.id=r.marksheet_id WHERE r.institution_id=:iid AND r.exam_id=:e AND r.student_id=:s
                         AND m.status IN ('approved','published')""", {"e": ex["id"], "s": s["id"]})
            if not res:
                st.caption("No approved/published results for this student in this exam.")
            else:
                ropts = {r["id"]: f"{r['subject']} · {r['obtained_marks']}/{r['max_marks']:g} ({r['status']})" for r in res}
                rid = c3.selectbox("Result", list(ropts), format_func=ropts.get)
                r = T.get("results", rid)
                with st.form("correct"):
                    x1, x2, x3 = st.columns([1, 1, 3])
                    new = x1.number_input("New marks", 0.0, float(r["max_marks"]), float(r["obtained_marks"] or 0), 0.5)
                    absent = x2.checkbox("Absent", bool(r["is_absent"]))
                    reason = x3.text_input("Reason *")
                    if st.form_submit_button("Apply correction", type="primary", icon=":material/edit_note:"):
                        session.attempt(exams.correct_result, a, rid, new, absent, reason, success="Correction recorded.", rerun=True)
        log = T.q("""SELECT c.created_at, st.first_name || ' ' || IFNULL(st.last_name,'') AS student, sub.name AS subject,
                     c.old_value, c.new_value, c.reason, u.full_name AS by_user FROM result_corrections c
                     JOIN results r ON r.id=c.result_id JOIN students st ON st.id=r.student_id JOIN subjects sub ON sub.id=r.subject_id
                     LEFT JOIN users u ON u.id=c.created_by WHERE c.institution_id=:iid ORDER BY c.created_at DESC""")
        if log:
            st.dataframe(pd.DataFrame(log), hide_index=True)
