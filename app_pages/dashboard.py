from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from ims import attendance, demo, fees, insights, session, ui
from ims.attendance import DAYS
from ims.security import role_label

a = session.require("dashboard.view")
T, S, P = a.tenant, a.settings, a.profile
today = date.today()
scope = a.class_scope()
scope_sql = "" if scope is None else f" AND class_id IN ({','.join(map(str, scope)) or '0'})"

active = T.count("students", "status='active'" + scope_sql)
staff_n = T.count("staff", "employment_status='active'")
classes_n = T.count("classes", "is_active=1")
day_stats = attendance.daily_summary(T, today.isoformat())
marked = sum(day_stats.values())
present = day_stats.get("present", 0) + day_stats.get("late", 0)
counted = marked - day_stats.get("excused", 0) - day_stats.get("leave", 0)
att_today = present / counted * 100 if counted else None

ui.hero(a.inst, S["accent"], P["title"], f"{a.inst['name']} — Dashboard",
        f"Welcome, {a.user['full_name']} · {role_label(a.user['role'])} · {ui.fmt_date(today.isoformat(), S)}",
        stats=[("Active students", ui.count_span(active)), (P["staff_plural"].capitalize(), ui.count_span(staff_n)),
               (P["classes"], ui.count_span(classes_n)),
               ("Attendance today", ui.count_span(att_today, 1, suffix="%") if att_today is not None else "—")])
st.write("")

# ---------------------------------------------------------------- demo data warning
if demo.has_demo_data(a.inst) or T.count("audit_log", "action='demo_data_loaded'") and T.count("students"):
    with st.container(border=True):
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.warning("**This workspace contains fictional demo data** (sample students, staff, fees and results). "
                   "Remove it before entering your real records.", icon=":material/science:")
        if a.user["is_owner"]:
            with c2.popover("Remove demo data", icon=":material/delete_sweep:", type="primary", width="stretch"):
                st.write("Deletes all students, staff, classes, fees, results and demo logins. "
                         "Your institution name, logo, settings and your own login are kept.")
                if st.button("Yes, remove everything and start fresh", type="primary", key="clear_demo"):
                    n = demo.clear_institution_data(a)
                    st.session_state.pop("demo_info", None)
                    session.flash(f"Demo data removed ({n} records). Your workspace is ready for real data.")
                    st.rerun()

# ---------------------------------------------------------------- demo credentials (instant demo only)
info = st.session_state.get("demo_info")
if info:
    with st.expander(":material/key: Demo workspace logins — try each role's view", expanded=True):
        st.markdown(f"You are signed in as the **owner**: `{info['username']}` / `{info['password']}` (save this to come back).")
        st.table({"Role": [r for r, _, _ in info["logins"]], "Username": [u for _, u, _ in info["logins"]],
                  "Password": [p for _, _, p in info["logins"]]})
        if st.button("Hide", key="hide_demo"):
            st.session_state.pop("demo_info")
            st.rerun()

# ---------------------------------------------------------------- getting started (until the basics exist)
if a.can("academics.manage", "students.manage", "fees.manage"):
    steps = [
        ("Add an academic year and term", T.count("terms") > 0, "app_pages/academics.py" if a.can("academics.manage") else None),
        (f"Create {P['classes'].lower()}", classes_n > 0, "app_pages/academics.py" if a.can("academics.manage") else None),
        (f"Add {P['subjects'].lower()}", T.count("subjects") > 0, "app_pages/academics.py" if a.can("academics.manage") else None),
        (f"Add {P['staff_plural'].lower()}", staff_n > 0, "app_pages/staff.py" if a.can("staff.manage") else None),
        ("Add or import students", T.count("students") > 0, "app_pages/students.py" if a.can("students.manage") else None),
        ("Set up fees", T.count("fee_structures") > 0, "app_pages/fees.py" if a.can("fees.manage") else None),
    ]
    if not all(d for _, d, _ in steps):
        ui.checklist(steps, "Getting started: set up your institution")

# ---------------------------------------------------------------- quick actions
qa = []
if a.can("students.manage"):
    qa.append(("app_pages/students.py", "Add student", ":material/person_add:", "New admission or CSV import"))
if a.can("attendance.mark"):
    qa.append(("app_pages/attendance.py", "Take attendance", ":material/fact_check:", "Mark today in seconds"))
if a.can("payments.record"):
    qa.append(("app_pages/fees.py", "Collect fee", ":material/point_of_sale:", "Payment + instant receipt"))
if a.can("marks.enter", "exams.manage"):
    qa.append(("app_pages/exams.py", "Enter marks", ":material/edit_note:", "Marksheets & results"))
if a.can("notices.manage"):
    qa.append(("app_pages/notices.py", "Post notice", ":material/campaign:", "Announce to anyone"))
if a.can("reports.academic", "reports.finance"):
    qa.append(("app_pages/reports.py", "Reports", ":material/monitoring:", "21 exportable reports"))
qa.append(("app_pages/command.py", "Find anything", ":material/search:", "Class, department, student…"))
ui.quick_actions(qa)
st.write("")

# ---------------------------------------------------------------- KPIs
new_30 = T.count("students", "admission_date>=?" + scope_sql, ((today - timedelta(days=30)).isoformat(),))
trend = attendance.trend(T, 30)
kpis = st.container(horizontal=True)
kpis.metric("Enrolled students", f"{active:,}", f"+{new_30} in 30 days" if new_30 else None,
            icon=":material/groups:", width="stretch")
kpis.metric("Attendance today", f"{att_today:.1f}%" if att_today is not None else "Not marked",
            f"{marked} marked" if marked else None, delta_color="off", icon=":material/fact_check:",
            chart_data=trend["rate"].tolist()[-14:] if not trend.empty else None, chart_type="area", width="stretch")
if a.can("insights.finance", "fees.view"):
    month = today.strftime("%Y-%m")
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    coll = T.q("SELECT substr(payment_date,1,7) AS m, SUM(amount) AS v FROM payments WHERE institution_id=:iid "
               "AND kind<>'credit_applied' GROUP BY m ORDER BY m", {})
    cmap = {r["m"]: r["v"] for r in coll}
    this_m, prev_m = cmap.get(month, 0), cmap.get(last_month, 0)
    open_inv = [i for i in fees.invoices(T, "i.status='issued'") if i["balance"] > fees.EPS]
    overdue = [i for i in open_inv if i["overdue_days"] > 0]
    kpis.metric("Collected this month", ui.money(this_m, S),
                f"{(this_m - prev_m) / prev_m * 100:+.0f}% vs last month" if prev_m else None,
                icon=":material/payments:", chart_data=[r["v"] for r in coll][-8:] or None, chart_type="bar",
                width="stretch")
    kpis.metric("Outstanding dues", ui.money(sum(i["balance"] for i in open_inv), S),
                f"{len(overdue)} overdue invoice(s)", delta_color="inverse" if overdue else "off",
                icon=":material/account_balance_wallet:", width="stretch")
pending = (T.count("marksheets", "status IN ('submitted','reviewed')") +
           T.count("discount_requests", "status='pending'") + T.count("leave_requests", "status='pending'") +
           T.count("change_requests", "status='pending'") +
           T.count("applications", "status IN ('submitted','under_review')"))
kpis.metric("Pending approvals", pending, icon=":material/pending_actions:", width="stretch")

# ---------------------------------------------------------------- charts
left, right = st.columns([1.35, 1], gap="medium")
with left, st.container(border=True):
    st.markdown("**Attendance trend** · last 30 days")
    if trend.empty:
        st.caption("No attendance has been marked yet.")
    else:
        df = trend.assign(date=pd.to_datetime(trend["date"]))
        base = alt.Chart(df).encode(x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b")))
        area = base.mark_area(opacity=.25, line=True, interpolate="monotone").encode(
            y=alt.Y("rate:Q", title="Attendance %", scale=alt.Scale(domain=[max(0, df["rate"].min() - 10), 100])))
        rule = alt.Chart(pd.DataFrame({"y": [S["attendance_threshold"]]})).mark_rule(strokeDash=[4, 4], color="#ef4444").encode(y="y:Q")
        pts = base.mark_circle(size=40).encode(y="rate:Q", tooltip=[alt.Tooltip("date:T"), alt.Tooltip("rate:Q", title="%")])
        st.altair_chart((area + rule + pts).properties(height=260, padding={"left": 12, "top": 8}))
with right, st.container(border=True):
    st.markdown(f"**Enrolment by {P['class'].lower()}**")
    rows = T.q("SELECT c.name || IFNULL(' ' || NULLIF(c.section,''),'') AS cls, COUNT(s.id) AS n FROM classes c "
               "LEFT JOIN students s ON s.class_id=c.id AND s.status='active' WHERE c.institution_id=:iid "
               "AND c.is_active=1 GROUP BY c.id ORDER BY c.name, c.section", {})
    if rows:
        st.altair_chart(alt.Chart(pd.DataFrame(rows)).mark_bar(cornerRadiusEnd=6).encode(
            y=alt.Y("cls:N", title=None, sort=None), x=alt.X("n:Q", title="Students"),
            color=alt.Color("n:Q", legend=None, scale=alt.Scale(scheme="purples")),
            tooltip=["cls", "n"]).properties(height=260))
    else:
        st.caption(f"No {P['classes'].lower()} yet.")

c1, c2 = st.columns([1.35, 1], gap="medium")
with c1, st.container(border=True):
    st.markdown("**Exam performance** · latest published results")
    perf = T.q("""SELECT s.name AS subject, ROUND(AVG(100.0*IFNULL(r.obtained_marks,0)/r.max_marks),1) AS avg,
                  SUM(100.0*IFNULL(r.obtained_marks,0)/r.max_marks >= :p AND r.is_absent=0) AS passed, COUNT(*) AS n
                  FROM results r JOIN marksheets m ON m.id=r.marksheet_id JOIN subjects s ON s.id=r.subject_id
                  WHERE r.institution_id=:iid AND m.status='published' AND r.is_exempt=0
                  AND m.exam_id=(SELECT m2.exam_id FROM marksheets m2 WHERE m2.institution_id=:iid AND m2.status='published'
                                 ORDER BY m2.published_at DESC LIMIT 1)
                  GROUP BY s.id ORDER BY avg DESC""", {"p": float(S["pass_percent"])})
    if perf:
        dfp = pd.DataFrame(perf)
        dfp["pass rate"] = (dfp["passed"] / dfp["n"] * 100).round(1)
        st.altair_chart(alt.Chart(dfp).mark_bar(cornerRadiusEnd=6).encode(
            x=alt.X("avg:Q", title="Average %", scale=alt.Scale(domain=[0, 100])), y=alt.Y("subject:N", sort="-x", title=None),
            color=alt.Color("avg:Q", legend=None, scale=alt.Scale(scheme="tealblues")),
            tooltip=["subject", "avg", "pass rate"]).properties(height=240))
    else:
        st.caption("No published results yet.")
with c2, st.container(border=True):
    st.markdown("**Today's schedule**")
    wd = DAYS[today.weekday()]
    me = a.staff_row()
    q = ("SELECT t.period, t.start_time, t.room, c.name || IFNULL(' ' || NULLIF(c.section,''),'') AS cls, "
         "s.name AS subject, st.full_name AS teacher FROM timetable t JOIN classes c ON c.id=t.class_id "
         "LEFT JOIN subjects s ON s.id=t.subject_id LEFT JOIN staff st ON st.id=t.staff_id "
         "WHERE t.institution_id=:iid AND t.day=:d")
    params = {"d": wd}
    if me and not a.can("classes.all"):
        q += " AND t.staff_id=:me"
        params["me"] = me["id"]
    q += " ORDER BY t.period LIMIT 8"
    sched = T.q(q, params)
    if sched:
        for r in sched:
            st.markdown(f":violet-badge[P{r['period']}] **{r['subject'] or 'Free'}** · {r['cls']}"
                        f" · {r['teacher'] or ''} {('· ' + r['room']) if r['room'] else ''}")
    else:
        st.caption(f"No lessons scheduled for {wd}.")

# ---------------------------------------------------------------- insights, events, notices
c3, c4 = st.columns([1.35, 1], gap="medium")
with c3, st.container(border=True):
    st.markdown("**Smart insights** · students who may need follow-up")
    st.caption("Offline rules: low attendance, failed papers and overdue fees. No cloud AI is used.")
    risk = insights.at_risk_students(T, S, include_fees=a.can("insights.finance", "fees.view"))
    if scope is not None and not risk.empty:
        allowed = {r["id"] for r in T.all("students", f"class_id IN ({','.join(map(str, scope)) or '0'})")}
        risk = risk[risk["student_id"].isin(allowed)]
    if risk.empty:
        st.success("No students flagged right now.", icon=":material/verified:")
    else:
        focus = risk[risk["Risk"].isin(["High", "Medium"])]
        h, m = (risk["Risk"] == "High").sum(), (risk["Risk"] == "Medium").sum()
        st.markdown(f":red-badge[{h} high] :orange-badge[{m} medium] :gray-badge[{len(risk) - h - m} low]")
        st.dataframe((focus if not focus.empty else risk).head(8).drop(columns=["student_id"]), hide_index=True,
                     column_config={"Attendance %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
                                    "Overdue": st.column_config.NumberColumn(format="%.0f")})
with c4:
    with st.container(border=True):
        st.markdown("**Upcoming events**")
        events = T.all("calendar_events", "end_date>=?", (today.isoformat(),), order="start_date LIMIT 5")
        icons = {"holiday": ":green-badge[Holiday]", "exam": ":red-badge[Exam]", "event": ":blue-badge[Event]",
                 "term": ":violet-badge[Term]"}
        for e in events:
            st.markdown(f"{icons.get(e['event_type'], ':gray-badge[Info]')} **{e['title']}** · "
                        f"{ui.fmt_date(e['start_date'], S)}")
        if not events:
            st.caption("Nothing scheduled.")
    with st.container(border=True):
        st.markdown("**Latest notices**")
        for n in T.all("notices", "expiry_date IS NULL OR expiry_date>=?", (today.isoformat(),),
                       order="created_at DESC LIMIT 3"):
            st.markdown(f"{':red-badge[Important]' if n['priority'] == 'high' else ''} **{n['title']}**")
            st.caption(ui.fmt_date(n["created_at"], S))
        if a.can("notices.view"):
            st.page_link("app_pages/notices.py", label="All notices", icon=":material/arrow_forward:")

if pending and a.can("approvals.view", "results.approve", "discounts.approve", "leave.approve"):
    st.page_link("app_pages/approvals.py", label=f"Review {pending} pending approval(s)", icon=":material/task_alt:")
ui.footer(f"{a.inst['name']} · {P['title']} · data stays on this server")
ui.maker_credit()
