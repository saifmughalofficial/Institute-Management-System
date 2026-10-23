"""Institution Management System — Streamlit entry point.

Run locally:   streamlit run app.py
Deploy:        push this folder to GitHub and pick app.py on Streamlit Community Cloud.
"""
import streamlit as st

from ims import MAKER_LINE, __version__, branding, db, session, ui
from ims.security import role_label

st.set_page_config(page_title="Institution Management System", page_icon=":material/school:",
                   layout="wide", initial_sidebar_state="expanded")


@st.cache_resource
def boot():
    db.init_db()
    return True


boot()

actor = session.current_actor()

if actor is None:
    st.session_state.pop("_actor", None)
    nav = st.navigation([st.Page("app_pages/welcome.py", title="Welcome", icon=":material/waving_hand:",
                                 default=True)], position="hidden")
    session.show_flashes()
    nav.run()
    st.stop()

st.session_state["_actor"] = actor
settings = actor.settings
profile = actor.profile
modules = settings["modules"]
inst = actor.inst
st.set_page_config(page_title=inst["name"])
ui.inject_css(settings["accent"])

logo = branding.logo_bytes(inst, settings["accent"])
st.logo(logo, size="large", icon_image=logo)


def page(path, title, icon, *perms, when=True, default=False):
    if not when or (perms and not actor.can(*perms)):
        return None
    return st.Page(path, title=title, icon=icon, default=default)


if actor.user["must_change_password"]:
    sections = {"": [st.Page("app_pages/account.py", title="Set a new password", icon=":material/key:", default=True)]}
else:
    portal_home = actor.is_portal
    sections = {
        "Overview": [
            page("app_pages/dashboard.py", "Dashboard", ":material/space_dashboard:", "dashboard.view",
                 default=not portal_home),
            page("app_pages/command.py", "Command center", ":material/terminal:", "dashboard.view"),
            page("app_pages/portal.py", "My portal", ":material/badge:", "portal.self", default=portal_home),
            page("app_pages/approvals.py", "Approvals", ":material/task_alt:", "approvals.view", "results.approve",
                 "discounts.approve", "leave.approve", "students.approve_transfer"),
        ],
        "People": [
            page("app_pages/admissions.py", "Admissions", ":material/how_to_reg:", "admissions.manage",
                 when=modules["admissions"]),
            page("app_pages/students.py", "Students", ":material/groups:", "students.view"),
            page("app_pages/staff.py", profile["staff_plural"].capitalize(), ":material/badge:", "staff.view",
                 "staff.manage", "staff_attendance.manage", "leave.approve"),
        ],
        "Academics": [
            page("app_pages/academics.py", profile["academics_page"], ":material/account_tree:", "academics.manage"),
            page("app_pages/registration.py", "Course registration", ":material/playlist_add_check:",
                 "academics.manage", "students.manage", when=profile["course_registration"]),
            page("app_pages/attendance.py", "Attendance", ":material/fact_check:", "attendance.view",
                 "attendance.mark"),
            page("app_pages/timetable.py", "Timetable & calendar", ":material/calendar_month:", "timetable.view",
                 "timetable.manage", when=modules["timetable"]),
            page("app_pages/homework.py", "Homework", ":material/assignment:", "homework.manage",
                 when=modules["homework"]),
            page("app_pages/exams.py", "Exams & results", ":material/grading:", "exams.view", "marks.enter",
                 "exams.manage", "results.review"),
        ],
        "Finance": [
            page("app_pages/fees.py", "Fees & payments", ":material/payments:", "fees.view", "payments.record"),
        ],
        "Communication & insights": [
            page("app_pages/notices.py", "Notices & circulars", ":material/campaign:", "notices.view"),
            page("app_pages/reports.py", "Reports", ":material/monitoring:", "reports.academic", "reports.finance"),
        ],
        "Modules": [
            page("app_pages/library.py", "Library", ":material/local_library:", "library.manage",
                 when=modules["library"]),
            page("app_pages/transport.py", "Transport", ":material/directions_bus:", "transport.manage",
                 when=modules["transport"]),
            page("app_pages/hostel.py", "Hostel", ":material/bed:", "hostel.manage", when=modules["hostel"]),
            page("app_pages/assets.py", "Inventory & assets", ":material/inventory_2:", "assets.manage",
                 when=modules["assets"]),
        ],
        "Administration": [
            page("app_pages/users.py", "Users & roles", ":material/manage_accounts:", "users.manage"),
            page("app_pages/settings.py", "Settings", ":material/settings:", "settings.manage"),
            page("app_pages/audit.py", "Audit log", ":material/policy:", "audit.view"),
            page("app_pages/backup.py", "Backup & restore", ":material/backup:", "backup.manage"),
        ],
        "Account": [page("app_pages/account.py", "My account", ":material/person:",
                         default=not actor.can("dashboard.view", "portal.self"))],
    }
    sections = {k: [p for p in v if p] for k, v in sections.items()}
    sections = {k: v for k, v in sections.items() if v}

nav = st.navigation(sections, position="sidebar", expanded=True)

with st.sidebar:
    ui.user_chip(actor.user["full_name"], f"{role_label(actor.user['role'])} · {profile['short']}")
    if actor.can("dashboard.view") and not actor.user["must_change_password"]:
        with st.form("global_search", border=False, clear_on_submit=True):
            q = st.text_input("Search", placeholder="Search class, student, staff…", label_visibility="collapsed",
                              icon=":material/search:")
            go_search = st.form_submit_button("Search", width="stretch", shortcut="Ctrl+K",
                                              help="Shortcut: Ctrl+K. Try 'class Grade 6' or a student's name.")
        if go_search:
            st.session_state["cmd_text"] = q.strip() or "help"
            st.switch_page("app_pages/command.py")
    pending = 0
    T = actor.tenant
    if actor.can("results.approve"):
        pending += T.count("marksheets", "status='reviewed'")
    if actor.can("results.review"):
        pending += T.count("marksheets", "status='submitted'")
    if actor.can("discounts.approve"):
        pending += T.count("discount_requests", "status='pending'")
    if actor.can("leave.approve"):
        pending += T.count("leave_requests", "status='pending'")
    if actor.can("students.approve_transfer"):
        pending += T.count("change_requests", "status='pending'")
    if pending:
        st.caption(f":orange-badge[:material/notifications_active: {pending} pending approval(s)]")
    if st.button("Sign out", icon=":material/logout:", width="stretch", key="signout"):
        actor.log("logout", "user", actor.uid)
        session.sign_out("Signed out.")
        st.rerun()
    st.caption(f"v{__version__} · offline-first · no paid APIs")
    st.caption(MAKER_LINE)

session.show_flashes()
nav.run()
