"""Landing page: first-run onboarding wizard, sign in and restore from backup."""
import os
import random
import time

import streamlit as st

from ims import accounts, backup, branding, db, demo, session, ui
from ims.profiles import ACCENTS, CURRENCIES, PROFILES

STEPS = ["Type", "Name", "Logo", "Administrator", "Review", "Ready"]
TYPE_TAGS = {
    "school": ["Grades & sections", "Guardians", "Report cards", "School fees"],
    "college": ["Programs", "Departments", "Semesters", "GPA results"],
    "university": ["Faculties", "Credit hours", "Course registration", "Transcripts"],
}


def signup_enabled() -> bool:
    value = os.environ.get("IMS_ALLOW_SIGNUP")
    if value is None:
        try:
            value = str(st.secrets.get("IMS_ALLOW_SIGNUP", "1"))
        except Exception:
            value = "1"
    return value.strip().lower() not in ("0", "false", "no", "off")


ob = st.session_state.setdefault("ob", {"step": 0, "type": None, "name": "", "currency": "PKR",
                                        "accent": "Indigo", "logo": None, "logo_name": "",
                                        "admin_name": "", "username": "", "email": "", "password": ""})
has_institutions = bool(db.scalar("SELECT COUNT(*) FROM institutions"))
view = st.session_state.setdefault("view", "login" if has_institutions else "setup")
if not has_institutions and view == "login":
    view = st.session_state["view"] = "setup"
if view == "setup" and has_institutions and not signup_enabled():
    view = st.session_state["view"] = "login"

ui.inject_css(ob["accent"], landing=True)


def go(step: int):
    ob["step"] = step
    st.rerun()


def header():
    st.html("""<div class="ims-center" style="margin-top:.2rem"><span class="ims-chip">School · College · University</span></div>
    <div class="ims-landing-title">Welcome to <span class="ims-gradient-text">Institution Management</span></div>
    <div class="ims-landing-sub">One configurable, multi-tenant platform. It runs free on your own computer
    and needs no paid API.</div>""")


# --------------------------------------------------------------------------- #
# Sign in
# --------------------------------------------------------------------------- #
def login_view():
    header()
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        st.html("""<div class="ims-glass">
          <div class="ims-feature"><i>1</i><div><b>Branded for every institution</b><span>Your name and logo appear on the dashboard, receipts, report cards and exports.</span></div></div>
          <div class="ims-feature"><i>2</i><div><b>Strict tenant isolation</b><span>Every record is tied to one institution. No institution can see another's students, fees or files.</span></div></div>
          <div class="ims-feature"><i>3</i><div><b>Roles with real permissions</b><span>Principal, accountant, teacher, registrar, parent, student and more, each checked on the server.</span></div></div>
          <div class="ims-feature"><i>4</i><div><b>Free and offline-first</b><span>Python, SQLite, Pillow and ReportLab only. No cloud API key needed.</span></div></div>
        </div>""")
    with right:
        with st.container(border=True, key="login_card"):
            st.subheader("Sign in", anchor=False)
            blocked_until = st.session_state.get("login_block", 0)
            with st.form("login", border=False):
                ident = st.text_input("Username or email", autocomplete="username")
                pw = st.text_input("Password", type="password", autocomplete="current-password")
                submitted = st.form_submit_button("Sign in", type="primary", width="stretch",
                                                  icon=":material/login:")
            if submitted:
                if time.time() < blocked_until:
                    st.error("Too many attempts from this browser. Wait a few minutes and try again.")
                else:
                    user, msg = accounts.authenticate(ident, pw)
                    if user:
                        session.sign_in(user)
                        session.flash(f"Welcome back, {user['full_name']}!")
                        st.rerun()
                    fails = st.session_state.get("login_fails", 0) + 1
                    st.session_state["login_fails"] = fails
                    if fails >= 10:
                        st.session_state["login_block"] = time.time() + 300
                        st.session_state["login_fails"] = 0
                    st.error(msg, icon=":material/error:")
            st.caption("Forgot your password? Ask your institution administrator to reset it.")
        if signup_enabled():
            c1, c2 = st.columns(2)
            if c1.button("Create a new institution", icon=":material/add_business:", width="stretch"):
                st.session_state["view"] = "setup"
                st.rerun()
            if c2.button("Restore from backup", icon=":material/settings_backup_restore:", width="stretch"):
                st.session_state["view"] = "restore"
                st.rerun()
        instant_demo_panel("login")


def instant_demo_panel(key: str):
    """One-click demo: creates a seeded workspace and signs straight in."""
    if not signup_enabled():
        return
    with st.container(border=True, key=f"demo_{key}"):
        st.markdown("**:material/bolt: Just exploring? Try an instant demo.** It's filled with fictional students, "
                    "fees, attendance and results, and you're signed in automatically.")
        row = st.container(horizontal=True)
        for kind in PROFILES:
            if row.button(f"{PROFILES[kind]['short']} demo", key=f"{key}_{kind}", icon=PROFILES[kind]["icon"], width="stretch"):
                ok, msg = accounts.signup_allowed(session.session_key())
                if not ok:
                    st.error(msg)
                    return
                with st.spinner(f"Building your {PROFILES[kind]['short'].lower()} demo with sample data…"):
                    uid, username, password, logins = demo.instant_demo(kind, session.session_key())
                user = db.query_one("SELECT * FROM users WHERE id=?", (uid,))
                session.sign_in(user)
                st.session_state["demo_info"] = {"username": username, "password": password, "logins": logins}
                session.flash("Your demo workspace is ready!")
                st.rerun()


# --------------------------------------------------------------------------- #
# Restore a workspace backup on a fresh server
# --------------------------------------------------------------------------- #
def restore_view():
    header()
    _, mid, _ = st.columns([1, 2, 1])
    with mid, st.container(border=True):
        st.subheader("Restore an institution from backup", anchor=False)
        st.write("Upload a backup ZIP downloaded from **Backup & restore**. This is useful when a hosted "
                 "copy restarts with an empty database. After it is restored, sign in with your usual account.")
        up = st.file_uploader("Backup file (.zip)", type=["zip"], max_upload_size=200)
        c1, c2 = st.columns(2)
        if c1.button("Restore", type="primary", disabled=up is None, width="stretch",
                     icon=":material/settings_backup_restore:"):
            ok, msg = accounts.signup_allowed(session.session_key())
            if not ok:
                st.error(msg)
            else:
                iid = session.attempt(backup.restore, up.getvalue())
                if iid:
                    db.execute("INSERT INTO signup_events(session_key, created_at) VALUES (?,?)",
                               (session.session_key(), db.now()))
                    name = db.scalar("SELECT name FROM institutions WHERE id=?", (iid,))
                    session.flash(f"{name} was restored. Sign in to continue.")
                    st.session_state["view"] = "login"
                    st.rerun()
        if c2.button("Back to sign in", width="stretch", icon=":material/arrow_back:"):
            st.session_state["view"] = "login"
            st.rerun()


# --------------------------------------------------------------------------- #
# Onboarding wizard
# --------------------------------------------------------------------------- #
def nav_buttons(back_to: int | None, next_label: str = "Continue", next_disabled=False, key="next"):
    cols = st.columns([1, 1, 1.4])
    back = cols[0].button("Back", icon=":material/arrow_back:", width="stretch", key=f"back_{key}",
                          disabled=back_to is None)
    nxt = cols[2].button(next_label, type="primary", icon=":material/arrow_forward:", icon_position="right",
                         width="stretch", key=key, disabled=next_disabled)
    if back and back_to is not None:
        go(back_to)
    return nxt


def step_type():
    st.html('<div class="ims-center" style="margin-bottom:10px;font-weight:650">Choose the type of institution '
            'you want to manage:</div>')
    cols = st.columns(3, gap="medium")
    for col, kind in zip(cols, PROFILES):
        p = PROFILES[kind]
        with col, st.container(key=f"typecard_{kind}"):
            chosen = ob["type"] == kind
            ui.type_card(kind, p["title"], p["tagline"], TYPE_TAGS[kind], chosen)
            if st.button(f"Selected: {p['short']}" if chosen else f"Select {p['short']}", key=f"pick_{kind}",
                         type="primary" if chosen else "secondary", width="stretch",
                         icon=":material/check_circle:" if chosen else ":material/radio_button_unchecked:"):
                ob["type"] = kind
                st.rerun()
    st.write("")
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        if nav_buttons(None, f"Continue with {PROFILES[ob['type']]['short']}" if ob["type"] else "Select a type first",
                       next_disabled=not ob["type"], key="n0"):
            go(1)
        instant_demo_panel("setup")


def step_name():
    p = PROFILES[ob["type"]]
    _, mid, _ = st.columns([1, 2, 1])
    with mid, st.container(border=True):
        st.markdown(f"**Institution type:** {p['icon']} {p['short']}")
        with st.form("name_form", border=False):
            name = st.text_input("Institution name", value=ob["name"], max_chars=120,
                                 placeholder=f"e.g. Bright Future {p['short']}  (press Enter to continue)")
            c1, c2 = st.columns(2)
            currency = c1.selectbox("Currency", CURRENCIES, index=CURRENCIES.index(ob["currency"]))
            accent = c2.selectbox("Brand colour", list(ACCENTS), index=list(ACCENTS).index(ob["accent"]))
            cols = st.columns([1, 1, 1.4])
            back = cols[0].form_submit_button("Back", icon=":material/arrow_back:", width="stretch")
            nxt = cols[2].form_submit_button("Continue", type="primary", icon=":material/arrow_forward:",
                                             icon_position="right", width="stretch")
        ob["currency"], ob["accent"] = currency, accent
        if back:
            ob["name"] = name
            go(0)
        if nxt:
            try:
                ob["name"] = accounts.validate_institution_name(name)
                go(2)
            except accounts.ValidationError as exc:
                st.error(str(exc), icon=":material/error:")


def step_logo():
    _, mid, _ = st.columns([1, 2, 1])
    with mid, st.container(border=True):
        st.markdown(f"**{ob['name']}** · logo *(optional)*")
        st.caption("PNG, JPG/JPEG or WebP, up to 2 MB. The file's content is checked, not only its extension.")
        up = st.file_uploader("Choose image", type=["png", "jpg", "jpeg", "webp"], max_upload_size=2,
                              key="logo_up")
        if up is not None:
            try:
                ob["logo"] = branding.validate_logo(up.name, up.getvalue())
                ob["logo_name"] = up.name
            except branding.UploadError as exc:
                ob["logo"] = None
                st.error(str(exc), icon=":material/error:")
        c1, c2 = st.columns([1, 3])
        c1.image(ob["logo"] or branding.monogram_png(ob["name"], ob["accent"]), width=96)
        c2.write("**Preview**")
        c2.caption(f"Using your uploaded logo ({ob['logo_name']})." if ob["logo"]
                   else "No logo yet. The initials monogram will be used everywhere.")
        if ob["logo"] and c2.button("Remove logo", icon=":material/delete:"):
            ob["logo"], ob["logo_name"] = None, ""
            st.rerun()
        cols = st.columns([1, 1, 1.4])
        if cols[0].button("Back", icon=":material/arrow_back:", width="stretch", key="back_n2"):
            go(1)
        if cols[1].button("Skip for now", width="stretch", key="skip_logo"):
            ob["logo"], ob["logo_name"] = None, ""
            go(3)
        if cols[2].button("Continue", type="primary", icon=":material/arrow_forward:", icon_position="right",
                          width="stretch", key="n2", disabled=ob["logo"] is None):
            go(3)


def step_admin():
    _, mid, _ = st.columns([1, 2, 1])
    with mid, st.container(border=True):
        st.markdown("**Create the first administrator** (the institution owner)")
        with st.form("admin_form", border=False):
            name = st.text_input("Full name", value=ob["admin_name"])
            c1, c2 = st.columns(2)
            username = c1.text_input("Username", value=ob["username"], autocomplete="username",
                                     help="Used to sign in. Letters, numbers and . _ @ - only.")
            email = c2.text_input("Email (optional, can also be used to sign in)", value=ob["email"])
            c3, c4 = st.columns(2)
            pw = c3.text_input("Password", type="password", autocomplete="new-password",
                               help="At least 8 characters with letters and numbers.")
            pw2 = c4.text_input("Confirm password", type="password", autocomplete="new-password")
            st.caption(":material/lock: Use at least 8 characters with letters and numbers. "
                       "Adding symbols and capitals makes it stronger.")
            cols = st.columns([1, 1, 1.4])
            back = cols[0].form_submit_button("Back", icon=":material/arrow_back:", width="stretch")
            nxt = cols[2].form_submit_button("Continue", type="primary", icon=":material/arrow_forward:",
                                             icon_position="right", width="stretch")
        if pw:
            ui.password_meter(pw)
        if back:
            go(2)
        if nxt:
            from ims.security import EMAIL_RE, USERNAME_RE, password_problems
            ob.update(admin_name=name.strip(), username=username.strip(), email=email.strip())
            errors = []
            if not name.strip():
                errors.append("Full name is required.")
            if not USERNAME_RE.match(username.strip()):
                errors.append("Username must be 3–60 characters: letters, numbers, . _ @ -")
            if email.strip() and not EMAIL_RE.match(email.strip()):
                errors.append("Enter a valid email address.")
            problems = password_problems(pw)
            if problems:
                errors.append("Password needs " + ", ".join(problems) + ".")
            if pw != pw2:
                errors.append("The passwords do not match.")
            if db.query_one("SELECT id FROM users WHERE username=? OR (email<>'' AND email=?) OR username=?",
                            (username.strip(), username.strip(), email.strip() or "\x00")):
                errors.append("That username or email is already taken.")
            if errors:
                for e in errors:
                    st.error(e, icon=":material/error:")
            else:
                ob["password"] = pw
                go(4)


def step_review():
    p = PROFILES[ob["type"]]
    if "captcha" not in st.session_state:
        st.session_state["captcha"] = (random.randint(2, 9), random.randint(2, 9))
    x, y = st.session_state["captcha"]
    _, mid, _ = st.columns([1, 2, 1])
    with mid, st.container(border=True):
        st.markdown("**Review your setup**")
        c1, c2 = st.columns([1, 3])
        c1.image(ob["logo"] or branding.monogram_png(ob["name"], ob["accent"]), width=90)
        c2.markdown(f"### {ob['name']}")
        c2.markdown(f"{p['icon']} **{p['title']}**  \n{p['tagline']}")
        st.table({"Setting": ["Institution type", "Institution name", "Logo", "Currency", "Brand colour",
                              "Administrator", "Username", "Email"],
                  "Value": [p["short"], ob["name"], "Uploaded" if ob["logo"] else "Skipped (monogram)",
                            ob["currency"], ob["accent"], ob["admin_name"], ob["username"], ob["email"] or "—"]})
        st.markdown("**Start with**")
        start = st.radio("Start with", ["An empty workspace (for my real institution)",
                                        "Fictional sample data (testing only)"], index=0, label_visibility="collapsed")
        load_demo = start.startswith("Fictional")
        if load_demo:
            st.warning("Sample students, staff, fees and results will be added to this workspace. "
                       "You can remove them later from the dashboard.", icon=":material/science:")
        answer = st.number_input(f"Quick check: what is {x} + {y}?", min_value=0, max_value=100, step=1, value=None)
        cols = st.columns([1, 1, 1.4])
        if cols[0].button("Back", icon=":material/arrow_back:", width="stretch", key="back_n4"):
            go(3)
        if cols[2].button("Create workspace", type="primary", icon=":material/rocket_launch:", width="stretch",
                          key="create_ws"):
            if answer != x + y:
                st.error("The quick check answer is not correct.", icon=":material/error:")
                st.session_state.pop("captcha", None)
                return
            try:
                with st.spinner("Creating your workspace…"):
                    iid, uid = accounts.create_workspace(
                        institution_type=ob["type"], name=ob["name"], logo_png=ob["logo"],
                        admin_name=ob["admin_name"], username=ob["username"], email=ob["email"],
                        password=ob["password"], currency=ob["currency"], accent=ob["accent"],
                        session_key=session.session_key())
                    logins = demo.seed(uid) if load_demo else []
            except accounts.ValidationError as exc:
                st.error(str(exc), icon=":material/error:")
                return
            ob["password"] = ""
            st.session_state.pop("captcha", None)
            st.session_state["created"] = {"uid": uid, "logins": logins}
            go(5)


def step_done():
    created = st.session_state.get("created")
    if not created:
        go(0)
    user = db.query_one("SELECT * FROM users WHERE id=?", (created["uid"],))
    inst = db.query_one("SELECT * FROM institutions WHERE id=?", (user["institution_id"],))
    ui.hero(inst, ob["accent"], "Workspace created", f"{inst['name']} — Dashboard",
            f"{PROFILES[inst['institution_type']]['title']} is ready. Welcome, {user['full_name']}.")
    st.balloons()
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        if created["logins"]:
            with st.container(border=True):
                st.markdown("**Demo logins** (fictional data, so change or disable these before real use)")
                st.table({"Role": [r for r, _, _ in created["logins"]],
                          "Username": [u for _, u, _ in created["logins"]],
                          "Password": [p for _, _, p in created["logins"]]})
        if st.button("Open my dashboard", type="primary", icon=":material/space_dashboard:", width="stretch"):
            st.session_state.pop("created", None)
            st.session_state.pop("ob", None)
            session.sign_in(user)
            session.flash(f"Welcome to {inst['name']}!")
            st.rerun()


def setup_view():
    header()
    ui.stepper(STEPS, len(STEPS) if ob["step"] == len(STEPS) - 1 else ob["step"])
    [step_type, step_name, step_logo, step_admin, step_review, step_done][ob["step"]]()
    if has_institutions and ob["step"] < 5:
        _, mid, _ = st.columns([1, 2, 1])
        if mid.button("I already have an account — sign in", type="tertiary", width="stretch",
                      icon=":material/login:"):
            st.session_state["view"] = "login"
            st.rerun()


{"login": login_view, "setup": setup_view, "restore": restore_view}[view]()
ui.footer("Institution Management System · Python + Streamlit + SQLite · free, offline-first, no paid APIs")
ui.maker_credit()
