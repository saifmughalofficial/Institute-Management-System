from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ims import academics, db, exams, session, ui, widgets

a = session.require("homework.manage")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header("Homework & assignments", "Set work for a class and track submissions")

t1, t2 = st.tabs(["Assign", "Track submissions"])
with t1:
    cid = widgets.pick_class(a, "hw_cls")
    if cid:
        subs = {s["id"]: s["name"] for s in academics.subjects_for_class(T, T.get("classes", cid))}
        scope = a.subject_scope(cid)
        if scope is not None:
            subs = {k: v for k, v in subs.items() if k in scope}
        with st.form("hw", clear_on_submit=True):
            c1, c2 = st.columns([2, 1])
            title = c1.text_input("Title")
            sub = c2.selectbox(P["subject"], list(subs), format_func=subs.get, index=None)
            desc = st.text_area("Instructions")
            due = st.date_input("Due date", date.today() + timedelta(days=3), min_value=date.today())
            if st.form_submit_button("Assign", type="primary", icon=":material/assignment_add:") and title.strip():
                with db.transaction():
                    hid = T.insert("homework", class_id=cid, subject_id=sub, title=title.strip(), description=desc,
                                   due_date=due.isoformat(), created_by=a.uid, created_at=db.now())
                    for s in exams.class_students(T, cid):
                        T.insert("homework_submissions", homework_id=hid, student_id=s["id"], status="pending",
                                 updated_at=db.now())
                session.flash("Homework assigned.")
                st.rerun()

with t2:
    scope = a.class_scope()
    hws = T.q("""SELECT h.id, h.title, h.due_date, c.name || IFNULL(' ' || NULLIF(c.section,''),'') AS cls, s.name AS subject, h.class_id,
                 (SELECT COUNT(*) FROM homework_submissions x WHERE x.homework_id=h.id AND x.status='submitted') AS done,
                 (SELECT COUNT(*) FROM homework_submissions x WHERE x.homework_id=h.id) AS total
                 FROM homework h JOIN classes c ON c.id=h.class_id LEFT JOIN subjects s ON s.id=h.subject_id
                 WHERE h.institution_id=:iid ORDER BY h.due_date DESC""")
    hws = [h for h in hws if scope is None or h["class_id"] in scope]
    if not hws:
        widgets.empty("No homework yet.")
    else:
        opts = {h["id"]: f"{h['title']} · {h['cls']} · due {ui.fmt_date(h['due_date'], S)} · {h['done']}/{h['total']}" for h in hws}
        hid = st.selectbox("Homework", list(opts), format_func=opts.get)
        subs = T.q("""SELECT x.id, st.first_name || ' ' || IFNULL(st.last_name,'') AS student, x.status, x.remarks
                      FROM homework_submissions x JOIN students st ON st.id=x.student_id
                      WHERE x.institution_id=:iid AND x.homework_id=:h ORDER BY st.first_name""", {"h": hid})
        df = pd.DataFrame(subs)
        ed = st.data_editor(df, hide_index=True, disabled=["student"], key=f"hw_ed_{hid}",
                            column_config={"id": None, "status": st.column_config.SelectboxColumn(
                                options=["pending", "submitted", "late", "excused"], required=True)})
        if st.button("Save statuses", type="primary", icon=":material/save:"):
            with db.transaction():
                for r in ed.itertuples():
                    T.update("homework_submissions", r.id, status=r.status, remarks=r.remarks, updated_at=db.now())
            session.flash("Saved.")
            st.rerun()
