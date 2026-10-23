import pandas as pd
import streamlit as st

from ims import accounts, people, session, ui, widgets
from ims.actor import Actor
from ims.security import PERMISSIONS, ROLES, generate_temp_password, role_label

a = session.require("users.manage")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header("Users & roles", "Accounts, role templates and individual permission grants")

names = ["Users", "Create user", "Edit user", "Role templates"] + (["Transfer ownership"] if a.user["is_owner"] else [])
tabs = dict(zip(names, st.tabs(names)))
users = T.all("users", order="full_name")

with tabs["Users"]:
    df = pd.DataFrame(users)[["full_name", "username", "email", "role", "is_owner", "is_active", "last_login"]]
    df["role"] = df["role"].map(role_label)
    st.dataframe(df, hide_index=True, column_config={"is_owner": st.column_config.CheckboxColumn("Owner"),
                                                     "is_active": st.column_config.CheckboxColumn("Active")})

with tabs["Create user"]:
    allowed = [r for r in ROLES if r != "owner" and (a.can("admins.manage") or r != "admin")]
    role = st.selectbox("Role", allowed, format_func=role_label, key="cu_role")
    with st.form("cu", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Full name")
        username = c2.text_input("Username")
        email = c3.text_input("Email (optional)")
        link_student = link_guardian = link_staff = None
        if role == "student":
            opts = widgets.student_options(a, statuses=None, scoped=False)
            link_student = st.selectbox("Student record", list(opts), format_func=opts.get, index=None)
        elif role == "parent":
            g = {x["id"]: f"{x['name']} · {x['phone'] or ''}" for x in T.all("guardians", order="name")}
            link_guardian = st.selectbox("Guardian record", list(g), format_func=g.get, index=None)
        else:
            sopts = {x["id"]: f"{x['full_name']} · {x['staff_no']}" for x in T.all("staff", "user_id IS NULL", order="full_name")}
            link_staff = st.selectbox("Link to staff record (needed for teachers)", list(sopts), format_func=sopts.get, index=None)
        temp = generate_temp_password()
        pw = st.text_input("Temporary password", temp, help="The user must change it at first sign-in.")
        if st.form_submit_button("Create user", type="primary", icon=":material/person_add:"):
            uid = session.attempt(accounts.create_user, a, full_name=name, username=username, email=email, role=role,
                                  password=pw, linked_student_id=link_student, linked_guardian_id=link_guardian,
                                  staff_id=link_staff)
            if uid:
                session.flash(f"User {username} created. Temporary password: {pw}")
                st.rerun()

with tabs["Edit user"]:
    uopts = {u["id"]: f"{u['full_name']} · {u['username']} · {role_label(u['role'])}" for u in users}
    uid = st.selectbox("User", list(uopts), format_func=uopts.get, key="eu_pick")
    u = T.require("users", uid)
    c1, c2 = st.columns(2, gap="large")
    with c1, st.container(border=True):
        st.markdown("**Account**")
        with st.form(f"eu_{uid}"):
            name = st.text_input("Full name", u["full_name"])
            email = st.text_input("Email", u["email"] or "")
            roles = [r for r in ROLES if r != "owner"] if not u["is_owner"] else ["owner"]
            role = st.selectbox("Role", roles, index=roles.index(u["role"]) if u["role"] in roles else 0, format_func=role_label,
                                disabled=bool(u["is_owner"]))
            active = st.toggle("Active", bool(u["is_active"]), disabled=bool(u["is_owner"]) or uid == a.uid)
            if st.form_submit_button("Save", type="primary", icon=":material/save:"):
                session.attempt(accounts.update_user, a, uid, full_name=name, email=email, role=role, is_active=active,
                                success="User updated.", rerun=True)
        with st.popover("Reset password", icon=":material/lock_reset:"):
            tmp = st.text_input("New temporary password", generate_temp_password(), key=f"rp_{uid}")
            if st.button("Reset", key=f"rpb_{uid}", type="primary"):
                if session.attempt(accounts.reset_password, a, uid, tmp):
                    session.flash(f"Password reset. Temporary password: {tmp}")
                    st.rerun()
        if u["locked_until"]:
            st.caption(f":orange-badge[Locked until {u['locked_until']}] (a password reset unlocks it)")
    with c2, st.container(border=True):
        st.markdown("**Permissions**")
        target = Actor.load(uid) if u["is_active"] else None
        base = set(ROLES.get(u["role"], {}).get("perms", set()))
        rows = T.all("user_permissions", "user_id=?", (uid,))
        grants = {r["perm"] for r in rows if r["granted"]}
        revokes = {r["perm"] for r in rows if not r["granted"]}
        if u["is_owner"]:
            st.info("The owner always has every permission.", icon=":material/shield_person:")
        elif u["role"] in ("parent", "student"):
            st.info("Portal accounts only see their own linked records.", icon=":material/shield:")
        else:
            label = lambda p: f"{PERMISSIONS[p][0]} · {PERMISSIONS[p][1]}"
            g = st.multiselect("Extra grants", [p for p in PERMISSIONS if p not in base and p != "portal.self"],
                               default=sorted(grants - base), format_func=label, key=f"g_{uid}")
            r = st.multiselect("Revoke from role template", sorted(base), default=sorted(revokes & base),
                               format_func=label, key=f"r_{uid}")
            if st.button("Save permissions", key=f"sp_{uid}", icon=":material/admin_panel_settings:"):
                session.attempt(accounts.set_permission_overrides, a, uid, set(g), set(r), success="Permissions saved.",
                                rerun=True)
        if target:
            with st.expander(f"Effective permissions ({len(target.perms)})"):
                st.write(", ".join(sorted(target.perms)))

with tabs["Role templates"]:
    matrix = pd.DataFrame({role_label(r): [p in v["perms"] for p in PERMISSIONS] for r, v in ROLES.items()},
                          index=[f"{PERMISSIONS[p][0]} · {PERMISSIONS[p][1]}" for p in PERMISSIONS])
    st.caption("Starting templates. Grant or revoke individual permissions per user in Edit user.")
    st.dataframe(matrix, column_config={c: st.column_config.CheckboxColumn(c) for c in matrix.columns}, height=600)

if "Transfer ownership" in tabs:
    with tabs["Transfer ownership"]:
        st.warning("You will become an administrator and the chosen user becomes the owner.", icon=":material/warning:")
        cands = {u["id"]: u["full_name"] for u in users if u["id"] != a.uid and u["is_active"] and u["role"] not in ("parent", "student")}
        if cands:
            with st.form("own"):
                new = st.selectbox("New owner", list(cands), format_func=cands.get)
                pw = st.text_input("Confirm with your password", type="password")
                if st.form_submit_button("Transfer ownership", type="primary"):
                    session.attempt(accounts.transfer_ownership, a, new, pw, success="Ownership transferred.", rerun=True)
        else:
            st.caption("Create another staff account first.")
