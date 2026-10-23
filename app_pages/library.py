from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ims import db, session, ui, widgets

a = session.require("library.manage")
T, S = a.tenant, a.settings
ui.page_header("Library", "Catalogue, copies, issue/return, renewals, overdue items and fines")
fine_day = float(S["library_fine_per_day"])

t1, t2, t3 = st.tabs(["Issue & return", "Catalogue", "Overdue"])
with t1:
    c1, c2 = st.columns(2, gap="large")
    with c1, st.container(border=True):
        st.markdown("**Issue a book**")
        avail = T.q("""SELECT bc.id, bc.barcode, b.title FROM book_copies bc JOIN books b ON b.id=bc.book_id
                       WHERE bc.institution_id=:iid AND bc.status='available' ORDER BY b.title""")
        copts = {r["id"]: f"{r['title']} · {r['barcode']}" for r in avail}
        cid = st.selectbox("Copy", list(copts), format_func=copts.get, index=None)
        s = widgets.pick_student(a, "lib_student", scoped=False)
        days = st.number_input("Loan days", 1, 90, int(S["library_loan_days"]))
        if st.button("Issue", type="primary", disabled=not (cid and s), icon=":material/output:"):
            with db.transaction():
                T.insert("book_issues", copy_id=cid, student_id=s["id"], issue_date=date.today().isoformat(),
                         due_date=(date.today() + timedelta(days=int(days))).isoformat(), issued_by=a.uid)
                T.update("book_copies", cid, status="issued")
            session.flash("Book issued.")
            st.rerun()
    with c2, st.container(border=True):
        st.markdown("**Return / renew**")
        out = T.q("""SELECT i.id, i.copy_id, i.due_date, i.renewals, b.title, bc.barcode, st.first_name || ' ' || IFNULL(st.last_name,'') AS who
                     FROM book_issues i JOIN book_copies bc ON bc.id=i.copy_id JOIN books b ON b.id=bc.book_id
                     LEFT JOIN students st ON st.id=i.student_id WHERE i.institution_id=:iid AND i.return_date IS NULL ORDER BY i.due_date""")
        iopts = {r["id"]: f"{r['title']} · {r['barcode']} · {r['who']} · due {r['due_date']}" for r in out}
        iid = st.selectbox("Issued item", list(iopts), format_func=iopts.get, index=None)
        if iid:
            r = next(x for x in out if x["id"] == iid)
            late = max(0, (date.today() - date.fromisoformat(r["due_date"])).days)
            st.caption(f"{late} day(s) late · fine {ui.money(late * fine_day, S)}")
            b = st.container(horizontal=True)
            if b.button("Return", type="primary", icon=":material/input:"):
                with db.transaction():
                    T.update("book_issues", iid, return_date=date.today().isoformat(), fine=late * fine_day)
                    T.update("book_copies", r["copy_id"], status="available")
                session.flash("Returned.")
                st.rerun()
            if b.button("Renew 7 days", icon=":material/autorenew:", disabled=r["renewals"] >= 2):
                T.update("book_issues", iid, due_date=(max(date.today(), date.fromisoformat(r["due_date"])) + timedelta(days=7)).isoformat(),
                         renewals=r["renewals"] + 1)
                st.rerun()
with t2:
    rows = T.q("""SELECT b.title, b.author, b.isbn, b.category, COUNT(bc.id) AS copies,
                  SUM(bc.status='available') AS available FROM books b LEFT JOIN book_copies bc ON bc.book_id=b.id
                  WHERE b.institution_id=:iid GROUP BY b.id ORDER BY b.title""")
    st.dataframe(pd.DataFrame(rows), hide_index=True) if rows else widgets.empty("Catalogue is empty.")
    with st.form("book", clear_on_submit=True):
        x1, x2, x3, x4 = st.columns([3, 2, 2, 1])
        title, author, isbn = x1.text_input("Title"), x2.text_input("Author"), x3.text_input("ISBN")
        n = x4.number_input("Copies", 1, 100, 1)
        if st.form_submit_button("Add book", icon=":material/add:") and title.strip():
            with db.transaction():
                bid = T.insert("books", title=title.strip(), author=author, isbn=isbn, category="General")
                for k in range(int(n)):
                    T.insert("book_copies", book_id=bid, barcode=f"LB-{bid:03d}-{k + 1}", status="available")
            st.rerun()
with t3:
    od = T.q("""SELECT b.title, bc.barcode, st.first_name || ' ' || IFNULL(st.last_name,'') AS borrower, i.due_date
                FROM book_issues i JOIN book_copies bc ON bc.id=i.copy_id JOIN books b ON b.id=bc.book_id
                LEFT JOIN students st ON st.id=i.student_id WHERE i.institution_id=:iid AND i.return_date IS NULL AND i.due_date < :d""",
             {"d": date.today().isoformat()})
    if od:
        df = pd.DataFrame(od)
        df["days late"] = df["due_date"].map(lambda d: (date.today() - date.fromisoformat(d)).days)
        df["fine"] = df["days late"] * fine_day
        st.dataframe(df, hide_index=True)
    else:
        st.success("No overdue books.", icon=":material/verified:")
