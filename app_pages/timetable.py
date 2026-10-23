from datetime import date

import pandas as pd
import streamlit as st

from ims import academics, attendance as att, session, ui, widgets

a = session.require("timetable.view", "timetable.manage")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header("Timetable & calendar", "Weekly timetables with clash detection, plus the academic calendar")
days = S["working_days"]

names = ["Class timetable", "Teacher timetable"]
if a.can("timetable.manage"):
    names += ["Edit timetable", "Clash scan"]
names.append("Academic calendar")
tabs = dict(zip(names, st.tabs(names)))


def grid(where, params):
    rows = T.q(f"""SELECT t.day, t.period, t.start_time, IFNULL(s.name,'—') AS subject, IFNULL(st.full_name,'') AS teacher,
                   c.name || IFNULL(' ' || NULLIF(c.section,''),'') AS cls, t.room
                   FROM timetable t JOIN classes c ON c.id=t.class_id LEFT JOIN subjects s ON s.id=t.subject_id
                   LEFT JOIN staff st ON st.id=t.staff_id WHERE t.institution_id=:iid AND {where}""", params)
    if not rows:
        widgets.empty("Nothing scheduled yet.")
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df


with tabs["Class timetable"]:
    cid = widgets.pick_class(a, "tt_cls", scoped=False)
    if cid:
        df = grid("t.class_id=:c", {"c": cid})
        if not df.empty:
            df["cell"] = df["subject"] + " · " + df["teacher"] + df["room"].apply(lambda r: f" ({r})" if r else "")
            wide = df.pivot_table(index="period", columns="day", values="cell", aggfunc="first").reindex(columns=[d for d in days if d in df["day"].unique()])
            st.dataframe(wide.fillna(""), width="stretch")
            widgets.export_buttons(a, "Class timetable", wide.fillna("").reset_index(), "tt_exp", perm=None)

with tabs["Teacher timetable"]:
    staff = {s["id"]: s["full_name"] for s in T.all("staff", "employment_status='active'", order="full_name")}
    me = a.staff_row()
    if staff:
        keys = list(staff)
        sid = st.selectbox(P["staff"], keys, format_func=staff.get, index=keys.index(me["id"]) if me and me["id"] in keys else 0)
        df = grid("t.staff_id=:s", {"s": sid})
        if not df.empty:
            df["cell"] = df["subject"] + " · " + df["cls"]
            st.dataframe(df.pivot_table(index="period", columns="day", values="cell", aggfunc="first").fillna(""), width="stretch")
            st.caption(f"{len(df)} period(s) a week")

if "Edit timetable" in tabs:
    with tabs["Edit timetable"]:
        cid = widgets.pick_class(a, "tte_cls", scoped=False)
        if cid:
            subs = {s["id"]: s["name"] for s in academics.subjects_for_class(T, T.get("classes", cid))}
            staff = {s["id"]: s["full_name"] for s in T.all("staff", "employment_status='active'", order="full_name")}
            with st.form("tt_add"):
                c1, c2, c3 = st.columns(3)
                day = c1.selectbox("Day", days)
                period = c2.number_input("Period", 1, int(S["periods_per_day"]) + 3, 1)
                room = c3.text_input("Room")
                c1, c2, c3, c4 = st.columns(4)
                sub = c1.selectbox(P["subject"], list(subs), format_func=subs.get, index=None)
                teacher = c2.selectbox(P["staff"], list(staff), format_func=staff.get, index=None)
                stt = c3.text_input("Start", "08:00")
                ent = c4.text_input("End", "08:45")
                if st.form_submit_button("Add lesson", type="primary", icon=":material/add:"):
                    session.attempt(att.add_timetable_entry, a, class_id=cid, subject_id=sub, staff_id=teacher, room=room,
                                    day=day, period=int(period), start_time=stt, end_time=ent, success="Lesson added.",
                                    rerun=True)
            rows = T.q("""SELECT t.id, t.day, t.period, IFNULL(s.name,'—') AS subject, IFNULL(st.full_name,'') AS teacher, t.room
                          FROM timetable t LEFT JOIN subjects s ON s.id=t.subject_id LEFT JOIN staff st ON st.id=t.staff_id
                          WHERE t.institution_id=:iid AND t.class_id=:c ORDER BY t.day, t.period""", {"c": cid})
            if rows:
                ropts = {r["id"]: f"{r['day']} P{r['period']} · {r['subject']} · {r['teacher']}" for r in rows}
                rid = st.selectbox("Remove a lesson", list(ropts), format_func=ropts.get, index=None)
                if rid and st.button("Remove lesson", icon=":material/delete:"):
                    T.delete("timetable", rid)
                    a.log("timetable_removed", "timetable", rid)
                    st.rerun()

    with tabs["Clash scan"]:
        issues = att.scan_conflicts(T)
        if issues:
            for i in issues:
                st.warning(i, icon=":material/warning:")
        else:
            st.success("No double-booked teachers, rooms or classes.", icon=":material/verified:")

with tabs["Academic calendar"]:
    events = T.all("calendar_events", order="start_date")
    colors = {"holiday": "green", "exam": "red", "event": "blue", "term": "violet"}
    upcoming = [e for e in events if e["end_date"] >= date.today().isoformat()]
    for e in upcoming[:15]:
        st.markdown(f":{colors.get(e['event_type'], 'gray')}-badge[{e['event_type'].title()}] **{e['title']}** · "
                    f"{ui.fmt_date(e['start_date'], S)}" + (f" → {ui.fmt_date(e['end_date'], S)}" if e["end_date"] != e["start_date"] else "")
                    + (f" · {e['description']}" if e["description"] else ""))
    if not upcoming:
        widgets.empty("No upcoming events.")
    with st.expander(f"Past events ({len(events) - len(upcoming)})"):
        past = [e for e in events if e not in upcoming]
        st.dataframe(pd.DataFrame(past)[["title", "event_type", "start_date", "end_date"]], hide_index=True) if past else st.caption("None")
    if a.can("calendar.manage"):
        with st.form("ev_add", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            title = c1.text_input("Event title")
            typ = c2.selectbox("Type", list(colors))
            sd, ed = c3.date_input("Start"), c4.date_input("End")
            desc = st.text_input("Description")
            if st.form_submit_button("Add event", icon=":material/event:") and title.strip():
                if ed < sd:
                    st.error("End date is before start date.")
                else:
                    T.insert("calendar_events", title=title.strip(), event_type=typ, start_date=sd.isoformat(),
                             end_date=ed.isoformat(), description=desc, created_by=a.uid)
                    st.rerun()
