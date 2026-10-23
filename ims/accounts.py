"""Login with lockout, workspace creation (onboarding) and user management."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import db
from .actor import Actor, PermissionDenied, audit
from .profiles import INSTITUTION_TYPES, default_settings
from .security import (EMAIL_RE, OWNER_ONLY_PERMS, PERMISSIONS, ROLES, USERNAME_RE,
                       hash_password, password_problems, verify_password)

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
SIGNUPS_PER_SESSION_PER_HOUR = 3
SIGNUPS_GLOBAL_PER_HOUR = 30


class ValidationError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
def authenticate(identifier: str, password: str) -> tuple[dict | None, str]:
    """Return (user, "") on success or (None, message). Messages never reveal
    whether the account exists."""
    generic = "Incorrect username/email or password."
    identifier = (identifier or "").strip()
    if not identifier or not password:
        return None, "Enter your username/email and password."
    user = db.query_one("SELECT * FROM users WHERE username=? OR (email<>'' AND email=?)",
                        (identifier, identifier))
    if not user:
        return None, generic
    now = datetime.now()
    if user["locked_until"] and datetime.fromisoformat(user["locked_until"]) > now:
        mins = int((datetime.fromisoformat(user["locked_until"]) - now).total_seconds() // 60) + 1
        return None, f"Too many failed attempts. Try again in {mins} minute(s)."
    if not verify_password(password, user["password_hash"]):
        failed = user["failed_attempts"] + 1
        locked = (now + timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds") \
            if failed >= MAX_FAILED_LOGINS else None
        db.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?",
                   (0 if locked else failed, locked, user["id"]))
        audit(user["institution_id"], user["id"], "login_failed", "user", user["id"],
              {"locked": bool(locked)})
        return None, generic
    if not user["is_active"]:
        return None, "This account has been disabled. Contact your administrator."
    inst = db.query_one("SELECT status FROM institutions WHERE id=?", (user["institution_id"],))
    if not inst or inst["status"] != "active":
        return None, "This institution workspace is not active."
    db.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=? WHERE id=?",
               (db.now(), user["id"]))
    audit(user["institution_id"], user["id"], "login", "user", user["id"])
    return user, ""


def change_password(actor: Actor, current: str, new: str):
    if not verify_password(current, actor.user["password_hash"]):
        raise ValidationError("Your current password is incorrect.")
    _check_password(new)
    if current == new:
        raise ValidationError("Choose a password different from the current one.")
    db.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
               (hash_password(new), actor.uid))
    actor.log("password_changed", "user", actor.uid)


def _check_password(pw: str):
    problems = password_problems(pw)
    if problems:
        raise ValidationError("Password needs " + ", ".join(problems) + ".")


def _check_identity(username: str, email: str, exclude_id: int | None = None):
    if not USERNAME_RE.match(username or ""):
        raise ValidationError("Username must be 3–60 characters: letters, numbers, . _ @ -")
    if email and not EMAIL_RE.match(email):
        raise ValidationError("Enter a valid email address.")
    # A username may not equal anyone's username or email, and the same for the email.
    clash = db.query_one(
        "SELECT id FROM users WHERE id<>? AND (username=? OR (email<>'' AND email=?)"
        " OR (?<>'' AND (username=? OR email=?)))",
        (exclude_id or 0, username, username, email or "", email or "", email or ""))
    if clash:
        raise ValidationError("That username or email is already in use.")


# --------------------------------------------------------------------------- #
# Onboarding: create an institution and its first administrator atomically
# --------------------------------------------------------------------------- #
def signup_allowed(session_key: str) -> tuple[bool, str]:
    hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    mine = db.scalar("SELECT COUNT(*) FROM signup_events WHERE session_key=? AND created_at>=?",
                     (session_key, hour_ago))
    total = db.scalar("SELECT COUNT(*) FROM signup_events WHERE created_at>=?", (hour_ago,))
    if mine >= SIGNUPS_PER_SESSION_PER_HOUR:
        return False, "You have created several workspaces recently. Please try again later."
    if total >= SIGNUPS_GLOBAL_PER_HOUR:
        return False, "Workspace creation is busy right now. Please try again later."
    return True, ""


def validate_institution_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise ValidationError("Institution name cannot be blank.")
    if len(name) < 3:
        raise ValidationError("Institution name must be at least 3 characters.")
    if len(name) > 120:
        raise ValidationError("Institution name must be 120 characters or fewer.")
    return name


def create_workspace(*, institution_type: str, name: str, logo_png: bytes | None,
                     admin_name: str, username: str, email: str, password: str,
                     currency: str = "PKR", accent: str = "Indigo",
                     session_key: str = "local") -> tuple[int, int]:
    """Create institution + owner account in one transaction. Returns (iid, uid)."""
    from . import branding

    if institution_type not in INSTITUTION_TYPES:
        raise ValidationError("Choose School, College or University.")
    name = validate_institution_name(name)
    admin_name = " ".join((admin_name or "").split())
    if not admin_name:
        raise ValidationError("Administrator name cannot be blank.")
    username = (username or "").strip()
    email = (email or "").strip()
    _check_identity(username, email)
    _check_password(password)
    ok, msg = signup_allowed(session_key)
    if not ok:
        raise ValidationError(msg)

    settings = default_settings(institution_type)
    settings["currency"] = currency
    settings["accent"] = accent
    saved_logo = None
    try:
        with db.transaction():
            iid = db.execute(
                "INSERT INTO institutions(name, institution_type, settings_json, created_at) VALUES (?,?,?,?)",
                (name, institution_type, json.dumps(settings), db.now()))
            if logo_png:
                saved_logo = branding.save_file(iid, "logo", logo_png, "png")
                db.execute("UPDATE institutions SET logo_path=? WHERE id=?", (saved_logo, iid))
            uid = db.execute(
                "INSERT INTO users(institution_id, username, email, full_name, password_hash, role,"
                " is_owner, created_at) VALUES (?,?,?,?,?,?,1,?)",
                (iid, username, email or None, admin_name, hash_password(password), "owner", db.now()))
            db.execute("INSERT INTO signup_events(session_key, created_at) VALUES (?,?)",
                       (session_key, db.now()))
            audit(iid, uid, "workspace_created", "institution", iid,
                  {"type": institution_type, "name": name, "logo": bool(logo_png)})
    except Exception:
        if saved_logo:
            branding.delete_file(iid, saved_logo)
        raise
    return iid, uid


# --------------------------------------------------------------------------- #
# User management (inside one institution)
# --------------------------------------------------------------------------- #
def _assert_can_manage(actor: Actor, role: str, target: dict | None = None):
    actor.require("users.manage")
    admin_roles = {"owner", "admin"}
    if role not in ROLES:
        raise ValidationError("Unknown role.")
    if role == "owner":
        raise PermissionDenied("The owner role cannot be assigned. Transfer ownership instead.")
    if (role in admin_roles or (target and (target["role"] in admin_roles or target["is_owner"]))) \
            and not actor.can("admins.manage"):
        raise PermissionDenied("Only the institution owner can create or change administrators.")
    if target and target["is_owner"] and not actor.user["is_owner"]:
        raise PermissionDenied("Only the owner can change the owner account.")


def create_user(actor: Actor, *, full_name: str, username: str, email: str, role: str,
                password: str, linked_student_id=None, linked_guardian_id=None,
                staff_id=None, must_change: bool = True) -> int:
    _assert_can_manage(actor, role)
    full_name = " ".join((full_name or "").split())
    if not full_name:
        raise ValidationError("Full name is required.")
    username, email = username.strip(), (email or "").strip()
    _check_identity(username, email)
    _check_password(password)
    T = actor.tenant
    if role == "student" and not linked_student_id:
        raise ValidationError("A student account must be linked to a student record.")
    if role == "parent" and not linked_guardian_id:
        raise ValidationError("A parent account must be linked to a guardian record.")
    with db.transaction():
        uid = T.insert("users", username=username, email=email or None, full_name=full_name,
                       password_hash=hash_password(password), role=role,
                       must_change_password=int(must_change),
                       linked_student_id=linked_student_id if role == "student" else None,
                       linked_guardian_id=linked_guardian_id if role == "parent" else None,
                       created_at=db.now())
        if staff_id:
            staff = T.require("staff", staff_id)
            if staff["user_id"]:
                raise ValidationError("That staff member already has a login.")
            T.update("staff", staff_id, user_id=uid)
        actor.log("user_created", "user", uid, {"username": username, "role": role})
    return uid


def update_user(actor: Actor, user_id: int, *, full_name: str, email: str, role: str,
                is_active: bool):
    T = actor.tenant
    target = T.require("users", user_id)
    _assert_can_manage(actor, "admin" if target["is_owner"] else role, target)
    if target["is_owner"]:
        role = "owner"
    if target["id"] == actor.uid and not is_active:
        raise ValidationError("You cannot disable your own account.")
    if target["is_owner"] and not is_active:
        raise ValidationError("The owner account cannot be disabled.")
    email = (email or "").strip()
    _check_identity(target["username"], email, exclude_id=target["id"])
    T.update("users", user_id, full_name=full_name.strip() or target["full_name"],
             email=email or None, role=role, is_active=int(is_active))
    actor.log("user_updated", "user", user_id,
              {"role": f"{target['role']}→{role}", "active": is_active})


def reset_password(actor: Actor, user_id: int, new_password: str):
    T = actor.tenant
    target = T.require("users", user_id)
    _assert_can_manage(actor, target["role"] if target["role"] != "owner" else "admin", target)
    _check_password(new_password)
    T.update("users", user_id, password_hash=hash_password(new_password),
             must_change_password=1, failed_attempts=0, locked_until=None)
    actor.log("password_reset", "user", user_id)


def set_permission_overrides(actor: Actor, user_id: int, grants: set[str], revokes: set[str]):
    T = actor.tenant
    target = T.require("users", user_id)
    actor.require("users.manage")
    if target["id"] == actor.uid:
        raise PermissionDenied("You cannot change your own permissions.")
    if target["is_owner"]:
        raise PermissionDenied("The owner always has every permission.")
    if target["role"] in ("parent", "student"):
        raise PermissionDenied("Portal accounts cannot receive staff permissions.")
    if target["role"] == "admin" and not actor.can("admins.manage"):
        raise PermissionDenied("Only the owner can change an administrator's permissions.")
    if (grants & OWNER_ONLY_PERMS) and not actor.user["is_owner"]:
        raise PermissionDenied("Only the owner can grant administration permissions.")
    unknown = (grants | revokes) - set(PERMISSIONS)
    if unknown:
        raise ValidationError(f"Unknown permissions: {', '.join(sorted(unknown))}")
    with db.transaction():
        db.execute("DELETE FROM user_permissions WHERE user_id=? AND institution_id=?",
                   (user_id, actor.iid))
        for p in sorted(grants):
            T.insert("user_permissions", user_id=user_id, perm=p, granted=1)
        for p in sorted(revokes - grants):
            T.insert("user_permissions", user_id=user_id, perm=p, granted=0)
        actor.log("permissions_changed", "user", user_id,
                  {"granted": sorted(grants), "revoked": sorted(revokes)})


def transfer_ownership(actor: Actor, new_owner_id: int, password: str):
    if not actor.user["is_owner"]:
        raise PermissionDenied("Only the owner can transfer ownership.")
    if not verify_password(password, actor.user["password_hash"]):
        raise ValidationError("Password is incorrect.")
    T = actor.tenant
    target = T.require("users", new_owner_id)
    if not target["is_active"] or target["role"] in ("parent", "student"):
        raise ValidationError("Choose an active staff account.")
    with db.transaction():
        T.update("users", new_owner_id, is_owner=1, role="owner")
        T.update("users", actor.uid, is_owner=0, role="admin")
        actor.log("ownership_transferred", "user", new_owner_id)
