import pandas as pd
import streamlit as st

from ims import academics, db, session, ui, widgets

a = session.require("academics.manage", "students.manage")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header("Course registration", "Register students into courses each semester, with credit-hour totals")
MAX_CREDITS = 21

term = widgets.pick_term(a, "reg_term")
if term:
    t1, t2 = st.tabs(["Student registration", "Register a whole cohort"])
    with t1:
        s = widgets.pick_student(a, "reg_student", scoped=False)
        if s:
            cls = T.get("classes", s["class_id"]) if s["class_id"] else None
            offered = academics.subjects_for_class(T, cls) if cls else T.all("subjects", order="name")
            reg = {r["subject_id"]: r for r in T.all("enrollments", "student_id=? AND term_id=? AND subject_id IS NOT NULL",
                                                      (s["id"], term["id"]))}
            df = pd.DataFrame({"id": [c["id"] for c in offered], "Code": [c["code"] for c in offered],
                               "Course": [c["name"] for c in offered], "Credits": [c["credit_hours"] for c in offered],
                               "Registered": [c["id"] in reg and reg[c["id"]]["status"] == "enrolled" for c in offered]})
            ed = st.data_editor(df, hide_index=True, disabled=["Code", "Course", "Credits"], column_config={"id": None},
                                key=f"reg_{s['id']}_{term['id']}")
            total = ed.loc[ed["Registered"], "Credits"].sum()
            st.metric("Credit hours selected", f"{total:g} / {MAX_CREDITS}")
            if st.button("Save registration", type="primary", icon=":material/save:", disabled=total > MAX_CREDITS):
                with db.transaction():
                    for r in ed.itertuples():
                        ex = reg.get(r.id)
                        if r.Registered and not ex:
                            T.insert("enrollments", student_id=s["id"], term_id=term["id"], subject_id=r.id,
                                     class_id=s["class_id"], program_id=s["program_id"],
                                     academic_year_id=term["academic_year_id"], status="enrolled", created_at=db.now())
                        elif ex:
                            T.update("enrollments", ex["id"], status="enrolled" if r.Registered else "dropped")
                    a.log("course_registration", "student", s["id"], {"term": term["id"], "credits": float(total)})
                session.flash("Registration saved.")
                st.rerun()
    with t2:
        cid = widgets.pick_class(a, "reg_cls", scoped=False)
        if cid:
            offered = academics.subjects_for_class(T, T.get("classes", cid))
            st.write(", ".join(f"{c['code'] or ''} {c['name']} ({c['credit_hours']:g})" for c in offered) or "No courses.")
            if st.button("Register every active student into these courses", type="primary", disabled=not offered):
                n = 0
                with db.transaction():
                    for s in T.all("students", "class_id=? AND status='active'", (cid,)):
                        for c in offered:
                            if not T.one("enrollments", "student_id=? AND term_id=? AND subject_id=?", (s["id"], term["id"], c["id"])):
                                T.insert("enrollments", student_id=s["id"], term_id=term["id"], subject_id=c["id"], class_id=cid,
                                         program_id=s["program_id"], academic_year_id=term["academic_year_id"],
                                         status="enrolled", created_at=db.now())
                                n += 1
                    a.log("cohort_registration", "class", cid, {"rows": n})
                session.flash(f"{n} registration(s) added.")
                st.rerun()
    st.divider()
    summary = T.q("""SELECT sub.code, sub.name AS course, sub.credit_hours, COUNT(e.id) AS registered
                     FROM enrollments e JOIN subjects sub ON sub.id=e.subject_id
                     WHERE e.institution_id=:iid AND e.term_id=:t AND e.status='enrolled' GROUP BY sub.id ORDER BY sub.code""",
                  {"t": term["id"]})
    st.markdown(f"**Registrations in {term['name']}**")
    st.dataframe(pd.DataFrame(summary), hide_index=True) if summary else st.caption("None yet.")
