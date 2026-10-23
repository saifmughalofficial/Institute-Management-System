from datetime import date, timedelta

import streamlit as st

from ims import db, pdf, people, session, ui, widgets

a = session.require("notices.view")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header("Notices & circulars", "Announcements for everyone, staff, students, parents or a single class")

# Audience filter: what this user may read
role = a.user["role"]
aud = ["all"] + (["parents"] if role == "parent" else ["students"] if role == "student" else ["staff", "students", "parents"])
my_classes = [T.get("students", s)["class_id"] for s in a.portal_student_ids()] if a.is_portal else None
rows = T.all("notices", f"audience IN ({','.join('?' * len(aud))}) AND (expiry_date IS NULL OR expiry_date>=?)",
             (*aud, date.today().isoformat()), order="created_at DESC")
if my_classes is not None:
    rows = [n for n in rows if not n["class_id"] or n["class_id"] in my_classes]
read = {r["notice_id"] for r in T.all("notice_reads", "user_id=?", (a.uid,))}

tabs = st.tabs(["Notice board"] + (["Publish notice"] if a.can("notices.manage") else []))
with tabs[0]:
    unread = [n for n in rows if n["id"] not in read]
    st.caption(f"{len(rows)} notice(s) · {len(unread)} unread")
    if not rows:
        widgets.empty("No notices right now.")
    for n in rows:
        with st.container(border=True):
            c1, c2 = st.columns([5, 2], vertical_alignment="center")
            badges = (":red-badge[Important] " if n["priority"] == "high" else "") + \
                     (":blue-badge[New] " if n["id"] not in read else "") + f":gray-badge[{n['audience']}]"
            c1.markdown(f"{badges}  \n**{n['title']}** · {ui.fmt_date(n['created_at'], S)}")
            c1.write(n["body"])
            if n["id"] not in read and c2.button("Mark as read", key=f"rd_{n['id']}", icon=":material/done:"):
                db.execute("INSERT OR IGNORE INTO notice_reads(institution_id, notice_id, user_id, read_at) VALUES (?,?,?,?)",
                           (a.iid, n["id"], a.uid, db.now()))
                st.rerun()
            author = (T.get("users", n["created_by"]) or {}).get("full_name", "")
            c2.download_button("Printable circular", lambda n=n, au=author: pdf.notice_pdf(a.inst, S, n, au),
                               f"Circular_{n['id']}.pdf", "application/pdf", key=f"pdf_{n['id']}", on_click="ignore",
                               icon=":material/print:")
            if a.can("notices.manage"):
                c2.caption(f"Read by {T.count('notice_reads', 'notice_id=?', (n['id'],))} user(s)")

if a.can("notices.manage"):
    with tabs[1], st.form("notice", clear_on_submit=True):
        title = st.text_input("Title")
        body = st.text_area("Message", height=150)
        c1, c2, c3, c4 = st.columns(4)
        audience = c1.selectbox("Audience", ["all", "staff", "students", "parents"])
        copts = people.class_options(a, only_scope=False)
        cls = c2.selectbox(f"Only {P['class'].lower()} (optional)", list(copts), format_func=copts.get, index=None)
        priority = c3.selectbox("Priority", ["normal", "high"])
        expiry = c4.date_input("Show until", date.today() + timedelta(days=30))
        if st.form_submit_button("Publish", type="primary", icon=":material/campaign:"):
            if not title.strip() or not body.strip():
                st.error("Title and message are required.")
            else:
                nid = T.insert("notices", title=title.strip(), body=body.strip(), audience=audience, class_id=cls,
                               priority=priority, expiry_date=expiry.isoformat(), created_by=a.uid, created_at=db.now())
                a.log("notice_published", "notice", nid)
                session.flash("Notice published.")
                st.rerun()
