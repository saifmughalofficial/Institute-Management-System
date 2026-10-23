from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from ims import insights, session, ui, widgets
from ims.reports import REPORTS

a = session.require("reports.academic", "reports.finance")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header("Reports", "Every report uses the same permissions and institution filter as the screens; exports are logged")

available = [r for r in REPORTS if a.can(r.perm)]
t1, t2 = st.tabs(["Report builder", "Insights (offline)"])
with t1:
    groups = sorted({r.group for r in available}, key=[r.group for r in REPORTS].index)
    c1, c2 = st.columns([1, 2])
    group = c1.segmented_control("Area", groups, default=groups[0]) or groups[0]
    reps = {r.key: r for r in available if r.group == group}
    key = c2.selectbox("Report", list(reps), format_func=lambda k: reps[k].title)
    rep = reps[key]
    f = {}
    cols = st.columns(4)
    i = 0
    if "dates" in rep.needs:
        f["start"] = cols[0].date_input("From", date.today() - timedelta(days=30)).isoformat()
        f["end"] = cols[1].date_input("To", date.today()).isoformat()
        i = 2
    else:
        f["start"], f["end"] = "1900-01-01", "2999-12-31"
    if "class" in rep.needs:
        with cols[i]:
            f["class_id"] = widgets.pick_class(a, "rp_cls", allow_none=a.class_scope() is None)
        i += 1
    if "exam" in rep.needs:
        with cols[i]:
            ex = widgets.pick_exam(a, "rp_exam")
            f["exam_id"] = ex["id"] if ex else None
        i += 1
    if "student" in rep.needs:
        with cols[i]:
            s = widgets.pick_student(a, "rp_student", statuses=None)
            f["student_id"] = s["id"] if s else None
    df = rep.build(a, f)
    st.markdown(f"#### {rep.title}")
    if df is None or df.empty:
        widgets.empty("No data for these filters.")
    else:
        st.caption(f"{len(df)} row(s) · {a.inst['name']} · generated {ui.fmt_date(date.today().isoformat(), S)}")
        st.dataframe(df, hide_index=True)
        widgets.export_buttons(a, rep.title, df, f"rp_{key}")

with t2:
    st.caption("Rule-based analysis that runs entirely on this server. No data leaves it and no AI API is used.")
    risk = insights.at_risk_students(T, S, include_fees=a.can("reports.finance"))
    scope = a.class_scope()
    if scope is not None and not risk.empty:
        ok = {r["id"] for r in T.all("students", f"class_id IN ({','.join(map(str, scope)) or '0'})")}
        risk = risk[risk["student_id"].isin(ok)]
    st.markdown("**Students needing follow-up**")
    if risk.empty:
        st.success("No students flagged.", icon=":material/verified:")
    else:
        st.dataframe(risk.drop(columns="student_id"), hide_index=True)
        widgets.export_buttons(a, "At-risk students", risk.drop(columns="student_id"), "risk_exp")
    if a.can("reports.finance"):
        fc = insights.collection_forecast(T)
        if not fc.empty:
            st.markdown("**Monthly fee collection and trend**")
            st.altair_chart(alt.Chart(fc).mark_bar(cornerRadiusEnd=6).encode(
                x=alt.X("month:N", title=None), y=alt.Y("collected:Q", title=S["currency"]),
                tooltip=["month", alt.Tooltip("collected:Q", format=",.0f")]).properties(height=240))
            if "next_month_estimate" in fc.attrs:
                st.metric("Simple trend estimate for next month", ui.money(fc.attrs["next_month_estimate"], S))
