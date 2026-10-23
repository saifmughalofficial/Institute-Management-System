from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from ims import academics, attendance as att, reports, session, ui, widgets

a = session.require("attendance.view", "attendance.mark")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header("Attendance", "Daily and " + (f"{P['subject'].lower()}-wise " if P["subject_attendance"] else "") +
               "attendance, registers, low-attendance alerts and corrections", tips=[
    "Choose the date and class. Everyone starts as **present**, so change only the absent or late students and press **Save**.",
    "**Mark everyone present** resets the whole list in one click.",
    "Changing earlier attendance counts as a correction: it needs a reason and is logged.",
    "**Register & summary** shows each student's percentage. Anyone below the threshold is flagged."])

names = (["Mark attendance"] if a.can("attendance.mark") else []) + ["Register & summary", "Corrections log"]
tabs = dict(zip(names, st.tabs(names)))

if "Mark attendance" in tabs:
    with tabs["Mark attendance"]:
        c1, c2, c3 = st.columns(3)
        day = c1.date_input("Date", date.today(), max_value=date.today())
        with c2:
            cid = widgets.pick_class(a, "att_cls")
        subject_id = None
        if cid and P["subject_attendance"]:
            subs = {s["id"]: s["name"] for s in academics.subjects_for_class(T, T.get("classes", cid))}
            scope = a.subject_scope(cid)
            if scope is not None:
                subs = {k: v for k, v in subs.items() if k in scope}
            subject_id = c3.selectbox("Session", [None] + list(subs),
                                      format_func=lambda k: "Daily (whole day)" if k is None else subs[k])
        if cid:
            studs = T.all("students", "class_id=? AND status='active'", (cid,), order="first_name, last_name")
            existing = {r["student_id"]: r for r in T.all(
                "attendance", "date=? AND IFNULL(subject_id,0)=?", (day.isoformat(), int(subject_id or 0)))}
            if not studs:
                widgets.empty("No active students in this class.")
            else:
                key = f"att_{cid}_{day}_{subject_id}"
                if st.button("Mark everyone present", icon=":material/done_all:"):
                    st.session_state[key + "_all"] = True
                default = "present"
                df = pd.DataFrame({
                    "id": [s["id"] for s in studs], "Admission no": [s["admission_no"] for s in studs],
                    "Student": [f"{s['first_name']} {s['last_name'] or ''}".strip() for s in studs],
                    "Status": ["present" if st.session_state.get(key + "_all") else existing.get(s["id"], {}).get("status", default)
                               for s in studs],
                    "Remark": [existing.get(s["id"], {}).get("remark") or "" for s in studs]})
                ed = st.data_editor(df, hide_index=True, key=key + str(st.session_state.get(key + "_all", "")),
                                    disabled=["Admission no", "Student"], height=min(38 * len(df) + 40, 560),
                                    column_config={"id": None, "Status": st.column_config.SelectboxColumn(
                                        options=att.STATUSES, required=True, width="medium")})
                counts = ed["Status"].value_counts()
                st.markdown(" ".join(f"{ui.badge_md(s)} {int(counts.get(s, 0))}" for s in att.STATUSES))
                is_edit = bool(existing) and (day.isoformat() != date.today().isoformat() or
                                              any(r["marked_by"] != a.uid for r in existing.values()))
                reason = st.text_input("Correction reason (needed when changing earlier attendance)") if is_edit else ""
                if st.button("Save attendance", type="primary", icon=":material/save:"):
                    marks = {int(r.id): (r.Status, r.Remark) for r in ed.itertuples()}
                    res = session.attempt(att.save_attendance, a, day.isoformat(), cid, subject_id, marks, reason)
                    if res:
                        st.session_state.pop(key + "_all", None)
                        session.flash(f"Saved · {res['inserted']} new, {res['updated']} updated, "
                                      f"{res['corrected']} correction(s).")
                        st.rerun()

with tabs["Register & summary"]:
    c1, c2, c3 = st.columns(3)
    start = c1.date_input("From", date.today() - timedelta(days=30), key="rs_from")
    end = c2.date_input("To", date.today(), key="rs_to")
    with c3:
        cid = widgets.pick_class(a, "rs_cls", allow_none=a.class_scope() is None)
    f = {"start": start.isoformat(), "end": end.isoformat(), "class_id": cid}
    pct = reports.attendance_percent(a, f)
    if pct.empty:
        widgets.empty("No attendance in this range.")
    else:
        thr = float(S["attendance_threshold"])
        low = pct[pct["Attendance %"] < thr]
        m = st.container(horizontal=True)
        m.metric("Students", len(pct), width="stretch")
        m.metric("Average attendance", f"{pct['Attendance %'].mean():.1f}%", width="stretch")
        m.metric(f"Below {thr:g}%", len(low), delta_color="inverse", width="stretch")
        st.dataframe(pct, hide_index=True, column_config={"Attendance %": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.1f%%")})
        widgets.export_buttons(a, "Attendance percentages", pct, "att_pct")
        tr = att.trend(T, (end - start).days)
        if not tr.empty:
            st.altair_chart(alt.Chart(tr.assign(date=pd.to_datetime(tr["date"]))).mark_line(point=True, interpolate="monotone")
                            .encode(x=alt.X("date:T", title=None), y=alt.Y("rate:Q", title="Institution attendance %"))
                            .properties(height=220))
        with st.expander("Daily register (P/A/L/E/LV)"):
            reg = reports.attendance_register(a, f)
            st.dataframe(reg, hide_index=True) if not reg.empty else st.caption("Choose a class to see its register.")
            widgets.export_buttons(a, "Attendance register", reg, "att_reg")

with tabs["Corrections log"]:
    rows = T.q("""SELECT c.created_at, st.first_name || ' ' || IFNULL(st.last_name,'') AS student, a.date,
                  c.old_status, c.new_status, c.reason, u.full_name AS corrected_by
                  FROM attendance_corrections c JOIN attendance a ON a.id=c.attendance_id
                  JOIN students st ON st.id=a.student_id LEFT JOIN users u ON u.id=c.created_by
                  WHERE c.institution_id=:iid ORDER BY c.created_at DESC LIMIT 500""")
    st.dataframe(pd.DataFrame(rows), hide_index=True) if rows else widgets.empty("No corrections recorded.")
