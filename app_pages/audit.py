from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ims import session, ui, widgets

a = session.require("audit.view")
T, S = a.tenant, a.settings
ui.page_header("Audit log", "Logins, permission changes, marks, results, fee waivers, refunds, exports and more")

c1, c2, c3, c4 = st.columns(4)
start = c1.date_input("From", date.today() - timedelta(days=30))
end = c2.date_input("To", date.today())
users = {u["id"]: u["full_name"] for u in T.all("users", order="full_name")}
who = c3.selectbox("User", [None] + list(users), format_func=lambda k: "Everyone" if k is None else users[k])
action = c4.text_input("Action contains", placeholder="e.g. payment, login, export")
sql = """SELECT l.created_at, u.full_name AS user, l.action, l.object_type, l.object_id, l.details
         FROM audit_log l LEFT JOIN users u ON u.id=l.user_id
         WHERE l.institution_id=:iid AND substr(l.created_at,1,10) BETWEEN :a AND :b"""
params = {"a": start.isoformat(), "b": end.isoformat()}
if who:
    sql += " AND l.user_id=:u"
    params["u"] = who
if action.strip():
    sql += " AND l.action LIKE :act"
    params["act"] = f"%{action.strip()}%"
rows = T.q(sql + " ORDER BY l.id DESC LIMIT 2000", params)
df = pd.DataFrame(rows)
st.caption(f"{len(df)} event(s) (latest 2000)")
if df.empty:
    widgets.empty("No events.")
else:
    m = st.container(horizontal=True)
    for act, n in df["action"].value_counts().head(5).items():
        m.metric(act.replace("_", " "), n, width="stretch")
    st.dataframe(df, hide_index=True, column_config={"details": st.column_config.TextColumn(width="large")})
    widgets.export_buttons(a, "Audit log", df, "audit_exp")
