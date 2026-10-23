from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ims import attendance as att, exams, fees, pdf, people, session, ui
from ims.attendance import DAYS

a = session.require("portal.self")
T, S, P = a.tenant, a.settings, a.profile
ids = a.portal_student_ids()
if not ids:
    st.warning("Your account is not linked to a student yet. Please contact the institution.", icon=":material/link_off:")
    st.stop()

if len(ids) > 1:
    opts = {i: people.full_name(T.get("students", i)) for i in ids}
    sid = st.segmented_control("Child", list(opts), format_func=opts.get, default=ids[0]) or ids[0]
else:
    sid = ids[0]
s = T.require("students", sid)
cls = T.get("classes", s["class_id"])
start = (date.today() - timedelta(days=90)).isoformat()
pct = att.percentages(T, start, date.today().isoformat(), student_ids=[sid])
att_pct = float(pct.iloc[0]["percent"]) if not pct.empty and pd.notna(pct.iloc[0]["percent"]) else None
invs = [i for i in fees.invoices(T, "i.student_id=:s", {"s": sid}) if i["state"] != "cancelled"]
due = sum(i["balance"] for i in invs)

ui.hero(a.inst, S["accent"], "Parent portal" if a.user["role"] == "parent" else "Student portal",
        people.full_name(s), f"{P['class']}: {people.class_label(cls)} · Admission no {s['admission_no']}",
        stats=[("Attendance (90 days)", ui.count_span(att_pct, 1, suffix="%") if att_pct is not None else "—"),
               ("Fee balance", ui.esc(ui.money(due, S))), ("Invoices", ui.count_span(len(invs)))])
st.write("")

t = st.tabs(["Results", "Attendance", "Timetable", "Fees & receipts", "Homework", "Notices"])
with t[0]:
    terms = T.q("""SELECT DISTINCT t.* FROM terms t JOIN exams e ON e.term_id=t.id JOIN marksheets m ON m.exam_id=e.id
                   JOIN results r ON r.marksheet_id=m.id WHERE t.institution_id=:iid AND r.student_id=:s AND m.status='published'
                   ORDER BY t.start_date DESC""", {"s": sid})
    if not terms:
        st.info("No published results yet.", icon=":material/hourglass_empty:")
    else:
        tid = st.selectbox(P["term"], [x["id"] for x in terms], format_func=lambda i: next(x["name"] for x in terms if x["id"] == i))
        term = T.get("terms", tid)
        rep = exams.term_report(T, S, sid, tid, published_only=True)
        m = st.container(horizontal=True)
        m.metric("Overall %", f"{rep['percent']:.1f}" if rep["percent"] is not None else "—", width="stretch")
        if P["gpa"]:
            m.metric("GPA", f"{rep['gpa']:.2f}" if rep["gpa"] is not None else "—", width="stretch")
        m.metric("Result", rep["result"], width="stretch")
        st.dataframe(pd.DataFrame(rep["lines"])[["subject", "obtained", "max", "percent", "grade"]], hide_index=True,
                     column_config={"percent": st.column_config.ProgressColumn("%", min_value=0, max_value=100, format="%.1f")})
        st.download_button(f"Download {P['result_doc'].lower()}", lambda: pdf.report_card_pdf(
            a.inst, S, s, people.class_label(cls), term["name"], rep, att_pct), f"{P['result_doc']}_{s['admission_no']}.pdf",
            "application/pdf", icon=":material/picture_as_pdf:", on_click="ignore", type="primary")
        if P["transcript"]:
            tr = exams.transcript(T, S, sid)
            prog = T.get("programs", s["program_id"])
            st.download_button("Download transcript", lambda: pdf.transcript_pdf(a.inst, S, s, (prog or {}).get("name"), tr),
                               f"Transcript_{s['admission_no']}.pdf", "application/pdf", icon=":material/school:", on_click="ignore")
with t[1]:
    if att_pct is not None:
        ui.progress(att_pct, "Attendance in the last 90 days")
    recs = T.all("attendance", "student_id=? AND date>=?", (sid, start), order="date DESC")
    st.dataframe(pd.DataFrame(recs)[["date", "status", "remark"]], hide_index=True) if recs else st.caption("No records.")
with t[2]:
    rows = T.q("""SELECT t.day, t.period, IFNULL(s.name,'—') || IFNULL(' · ' || st.full_name,'') AS cell FROM timetable t
                  LEFT JOIN subjects s ON s.id=t.subject_id LEFT JOIN staff st ON st.id=t.staff_id
                  WHERE t.institution_id=:iid AND t.class_id=:c""", {"c": s["class_id"] or 0})
    if rows:
        df = pd.DataFrame(rows).pivot_table(index="period", columns="day", values="cell", aggfunc="first")
        st.dataframe(df.reindex(columns=[d for d in DAYS if d in df.columns]).fillna(""), width="stretch")
    else:
        st.caption("No timetable published.")
with t[3]:
    if not invs:
        st.caption("No invoices.")
    for inv in invs:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            c1.markdown(f"**{inv['invoice_no']}** · {inv['period_label'] or ''} {ui.badge_md(inv['state'])}  \n"
                        f"Total {ui.money(inv['total'], S)} · paid {ui.money(inv['paid'], S)} · balance **{ui.money(inv['balance'], S)}**"
                        f" · due {ui.fmt_date(inv['due_date'], S)}")
            c2.download_button("Invoice", lambda inv=inv: pdf.invoice_pdf(T, a.inst, S, inv, s, people.class_label(cls)),
                               f"{inv['invoice_no']}.pdf", "application/pdf", key=f"pi_{inv['id']}", on_click="ignore",
                               icon=":material/description:")
            for p_ in T.all("payments", "invoice_id=? AND kind<>'reversal' AND is_reversed=0", (inv["id"],)):
                c2.download_button(f"Receipt {p_['receipt_no']}", lambda p_=p_, inv=inv: pdf.receipt_pdf(
                    T, a.inst, S, p_, fees.invoice(T, inv["id"]), s, ""), f"{p_['receipt_no']}.pdf", "application/pdf",
                    key=f"pr_{p_['id']}", on_click="ignore", icon=":material/receipt_long:")
with t[4]:
    hw = T.q("""SELECT h.title, h.description, h.due_date, s.name AS subject, x.status FROM homework h
                LEFT JOIN subjects s ON s.id=h.subject_id LEFT JOIN homework_submissions x ON x.homework_id=h.id AND x.student_id=:s
                WHERE h.institution_id=:iid AND h.class_id=:c ORDER BY h.due_date DESC LIMIT 30""", {"s": sid, "c": s["class_id"] or 0})
    st.dataframe(pd.DataFrame(hw), hide_index=True) if hw else st.caption("No homework.")
with t[5]:
    st.page_link("app_pages/notices.py", label="Open the notice board", icon=":material/campaign:")
