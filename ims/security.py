"""Password hashing, permissions and role templates."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets

ITERATIONS = int(os.environ.get("IMS_PBKDF2_ITERATIONS", "260000"))


# --------------------------------------------------------------------------- #
# Passwords (PBKDF2-SHA256 from the standard library; never stored in plain text)
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                     base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(digest, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


COMMON_PASSWORDS = {"password", "password1", "12345678", "123456789", "qwerty123",
                    "admin123", "letmein1", "welcome1", "iloveyou1", "abc12345"}


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[A-Za-z]", password):
        problems.append("at least one letter")
    if not re.search(r"\d", password):
        problems.append("at least one number")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("not a commonly used password")
    return problems


USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{3,60}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def generate_temp_password() -> str:
    return "Tmp-" + secrets.token_urlsafe(6) + "9"


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
PERMISSIONS: dict[str, tuple[str, str]] = {
    "dashboard.view": ("General", "View the institution dashboard"),
    "insights.finance": ("General", "See fee summaries on the dashboard"),
    "approvals.view": ("General", "Open the approvals queue"),
    "students.view": ("Students", "View student records"),
    "students.manage": ("Students", "Create and edit students and guardians"),
    "students.import": ("Students", "Bulk import students from CSV"),
    "students.documents": ("Students", "Upload and download student documents"),
    "students.approve_transfer": ("Students", "Approve transfers and withdrawals"),
    "admissions.manage": ("Students", "Manage admission applications"),
    "staff.view": ("Staff", "View staff records"),
    "staff.manage": ("Staff", "Create and edit staff records"),
    "staff_attendance.manage": ("Staff", "Mark staff attendance"),
    "leave.request": ("Staff", "Apply for leave"),
    "leave.approve": ("Staff", "Approve or reject leave"),
    "academics.manage": ("Academics", "Manage years, terms, classes, programs and subjects"),
    "classes.all": ("Academics", "Access every class (not only assigned ones)"),
    "timetable.view": ("Academics", "View timetables"),
    "timetable.manage": ("Academics", "Edit timetables"),
    "calendar.manage": ("Academics", "Edit the academic calendar"),
    "homework.manage": ("Academics", "Set homework and track submissions"),
    "attendance.view": ("Attendance", "View attendance"),
    "attendance.mark": ("Attendance", "Mark attendance"),
    "attendance.correct": ("Attendance", "Correct past attendance (reason required)"),
    "fees.view": ("Finance", "View invoices and payments"),
    "fees.manage": ("Finance", "Fee setup, invoices, cancellations, late fees"),
    "payments.record": ("Finance", "Record payments and apply advance credit"),
    "payments.reverse": ("Finance", "Reverse payments and refund credit"),
    "discounts.approve": ("Finance", "Approve discounts above the threshold"),
    "scholarships.manage": ("Finance", "Manage scholarships / financial aid"),
    "exams.view": ("Exams", "View exams and published results"),
    "exams.manage": ("Exams", "Create exams and marksheets"),
    "marks.enter": ("Exams", "Enter marks for assigned subjects"),
    "results.review": ("Exams", "Review submitted marksheets"),
    "results.approve": ("Exams", "Approve reviewed marksheets"),
    "results.publish": ("Exams", "Publish approved results"),
    "results.correct": ("Exams", "Correct approved/published marks"),
    "notices.view": ("Communication", "Read notices"),
    "notices.manage": ("Communication", "Publish notices"),
    "reports.academic": ("Reports", "Academic and student reports"),
    "reports.finance": ("Reports", "Financial reports"),
    "reports.export": ("Reports", "Export reports (logged)"),
    "library.manage": ("Modules", "Library"),
    "transport.manage": ("Modules", "Transport"),
    "hostel.manage": ("Modules", "Hostel"),
    "assets.manage": ("Modules", "Inventory and assets"),
    "users.manage": ("Administration", "Manage user accounts"),
    "admins.manage": ("Administration", "Create or disable administrators"),
    "settings.manage": ("Administration", "Institution settings and branding"),
    "audit.view": ("Administration", "View the audit log"),
    "backup.manage": ("Administration", "Backup and restore"),
    "portal.self": ("Portal", "Student / parent self-service portal"),
}

# Only the institution owner may hand these out as individual grants.
OWNER_ONLY_PERMS = {"admins.manage", "users.manage", "settings.manage", "backup.manage"}

_ALL_STAFF = set(PERMISSIONS) - {"portal.self"}

ROLES: dict[str, dict] = {
    "owner": {"label": "Institution owner", "perms": _ALL_STAFF},
    "admin": {"label": "Administrator", "perms": _ALL_STAFF - {"admins.manage"}},
    "principal": {"label": "Principal / head", "perms": {
        "dashboard.view", "insights.finance", "approvals.view", "students.view",
        "students.approve_transfer", "admissions.manage", "staff.view", "leave.approve",
        "leave.request", "classes.all", "timetable.view", "calendar.manage",
        "attendance.view", "fees.view", "discounts.approve", "exams.view",
        "results.review", "results.approve", "results.publish", "results.correct",
        "notices.view", "notices.manage", "reports.academic", "reports.finance",
        "reports.export", "audit.view"}},
    "vice_principal": {"label": "Vice principal / academic head", "perms": {
        "dashboard.view", "approvals.view", "students.view", "staff.view", "classes.all",
        "timetable.view", "timetable.manage", "calendar.manage", "attendance.view",
        "attendance.correct", "staff_attendance.manage", "exams.view", "results.review",
        "notices.view", "notices.manage", "reports.academic", "leave.request"}},
    "exam_controller": {"label": "Exam controller", "perms": {
        "dashboard.view", "approvals.view", "students.view", "classes.all", "exams.view",
        "exams.manage", "results.review", "results.publish", "timetable.view",
        "notices.view", "reports.academic", "leave.request"}},
    "accountant": {"label": "Accountant / fee manager", "perms": {
        "dashboard.view", "insights.finance", "students.view", "classes.all", "fees.view",
        "fees.manage", "payments.record", "scholarships.manage", "notices.view",
        "reports.finance", "reports.export", "leave.request"}},
    "cashier": {"label": "Cashier", "perms": {
        "dashboard.view", "students.view", "classes.all", "fees.view", "payments.record",
        "notices.view", "leave.request"}},
    "teacher": {"label": "Teacher / lecturer", "perms": {
        "dashboard.view", "students.view", "attendance.view", "attendance.mark",
        "exams.view", "marks.enter", "homework.manage", "timetable.view",
        "notices.view", "leave.request"}},
    "registrar": {"label": "Admission officer / registrar", "perms": {
        "dashboard.view", "students.view", "students.manage", "students.import",
        "students.documents", "admissions.manage", "classes.all", "timetable.view",
        "notices.view", "reports.academic", "reports.export", "leave.request"}},
    "librarian": {"label": "Librarian", "perms": {
        "dashboard.view", "library.manage", "notices.view", "leave.request"}},
    "transport_manager": {"label": "Transport manager", "perms": {
        "dashboard.view", "transport.manage", "notices.view", "leave.request"}},
    "hostel_warden": {"label": "Hostel warden", "perms": {
        "dashboard.view", "hostel.manage", "notices.view", "leave.request"}},
    "store_keeper": {"label": "Store / assets keeper", "perms": {
        "dashboard.view", "assets.manage", "notices.view", "leave.request"}},
    "parent": {"label": "Parent / guardian", "perms": {"portal.self", "notices.view"}},
    "student": {"label": "Student", "perms": {"portal.self", "notices.view"}},
}

STAFF_ROLES = [r for r in ROLES if r not in ("parent", "student", "owner")]


def role_label(role: str) -> str:
    return ROLES.get(role, {}).get("label", role.replace("_", " ").title())


def effective_permissions(role: str, is_owner: bool, overrides) -> set[str]:
    """Role template + per-user grants/revocations. The owner always has everything."""
    if is_owner:
        return set(_ALL_STAFF)
    perms = set(ROLES.get(role, {}).get("perms", set()))
    for perm, granted in overrides:
        if perm not in PERMISSIONS:
            continue
        if granted:
            perms.add(perm)
        else:
            perms.discard(perm)
    if role in ("parent", "student"):
        # Portal accounts can never receive staff permissions.
        perms &= {"portal.self", "notices.view"}
    return perms
