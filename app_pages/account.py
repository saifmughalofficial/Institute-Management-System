from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ims import accounts, attendance as att, session, ui
from ims.security import role_label

a = session.require()
T, S = a.tenant, a.settings
forced = bool(a.user["must_change_password"])
ui.page_header("Set a new password" if forced else "My account",
               "Your administrator asked you to choose a new password before continuing." if forced else
               f"{a.user['full_name']} · {role_label(a.user['role'])} · {a.inst['name']}")

c1, c2 = st.columns(2, gap="large")
with c1, st.container(border=True):
    st.markdown("**Change password**")
    with st.form("pw", clear_on_submit=True):
        cur = st.text_input("Current password", type="password")
        new = st.text_input("New password", type="password", help="At least 8 characters with letters and numbers.")
        new2 = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Update password", type="primary", icon=":material/key:"):
            if new != new2:
                st.error("The new passwords do not match.")
            elif session.attempt(accounts.change_password, a, cur, new, success="Password updated."):
                st.rerun()
    if forced:
        if st.button("Sign out", icon=":material/logout:"):
            session.sign_out()
            st.rerun()
with c2, st.container(border=True):
    st.markdown("**Profile**")
    st.table({"Field": ["Username", "Email", "Role", "Last sign-in"],
              "Value": [a.user["username"], a.user["email"] or "—", role_label(a.user["role"]),
                        ui.fmt_date(a.user["last_login"], S)]})

staff = a.staff_row()
if not forced and staff and a.can("leave.request"):
    st.markdown("### My leave")
    bal = att.leave_balance(T, staff["id"], S)
    m = st.container(horizontal=True)
    for k, v in bal.items():
        m.metric(f"{k} leave left", f"{v['left']:g} / {v['allowed']}", width="stretch")
    with st.form("leave", clear_on_submit=True):
        x1, x2, x3 = st.columns(3)
        typ = x1.selectbox("Type", list(S["leave_allowance"]))
        f = x2.date_input("From", date.today() + timedelta(days=1))
        t = x3.date_input("To", date.today() + timedelta(days=1))
        reason = st.text_input("Reason")
        if st.form_submit_button("Apply for leave", type="primary", icon=":material/event_busy:"):
            session.attempt(att.request_leave, a, typ, f, t, reason, success="Leave request sent.", rerun=True)
    mine = T.all("leave_requests", "staff_id=?", (staff["id"],), order="created_at DESC")
    if mine:
        st.dataframe(pd.DataFrame(mine)[["leave_type", "from_date", "to_date", "days", "status", "reason"]], hide_index=True)
