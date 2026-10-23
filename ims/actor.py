"""The signed-in user, their institution and permissions.

Services receive an :class:`Actor` and check permissions themselves, so hiding
a button is never the only protection.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import db
from .profiles import PROFILES, load_settings
from .security import effective_permissions


class PermissionDenied(PermissionError):
    pass


SENSITIVE_KEYS = ("password", "token", "secret", "hash")


def audit(iid: int, user_id, action: str, object_type: str | None = None,
          object_id=None, details: dict | str | None = None):
    """Append to the audit log. Values under password/token-like keys are dropped."""
    if isinstance(details, dict):
        details = json.dumps({k: v for k, v in details.items()
                              if not any(s in k.lower() for s in SENSITIVE_KEYS)},
                             default=str)
    db.execute(
        "INSERT INTO audit_log(institution_id, user_id, action, object_type, object_id, details, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (int(iid), user_id, action, object_type, object_id, details, db.now()))


@dataclass
class Actor:
    user: dict
    inst: dict
    perms: set = field(default_factory=set)

    @classmethod
    def load(cls, user_id: int) -> "Actor | None":
        user = db.query_one("SELECT * FROM users WHERE id=?", (int(user_id),))
        if not user or not user["is_active"]:
            return None
        inst = db.query_one("SELECT * FROM institutions WHERE id=?", (user["institution_id"],))
        if not inst or inst["status"] != "active":
            return None
        overrides = [(r["perm"], r["granted"]) for r in db.query(
            "SELECT perm, granted FROM user_permissions WHERE user_id=? AND institution_id=?",
            (user["id"], inst["id"]))]
        perms = effective_permissions(user["role"], bool(user["is_owner"]), overrides)
        return cls(user=user, inst=inst, perms=perms)

    # identity ---------------------------------------------------------------
    @property
    def uid(self) -> int:
        return self.user["id"]

    @property
    def iid(self) -> int:
        return self.inst["id"]

    @property
    def tenant(self) -> db.Tenant:
        return db.Tenant(self.iid)

    @property
    def profile(self) -> dict:
        return PROFILES[self.inst["institution_type"]]

    @property
    def settings(self) -> dict:
        return load_settings(self.inst)

    @property
    def is_portal(self) -> bool:
        return self.user["role"] in ("parent", "student")

    # permissions ------------------------------------------------------------
    def can(self, *perms: str) -> bool:
        return any(p in self.perms for p in perms)

    def require(self, *perms: str):
        if not self.can(*perms):
            raise PermissionDenied("You do not have permission to do this.")

    def log(self, action: str, object_type=None, object_id=None, details=None):
        audit(self.iid, self.uid, action, object_type, object_id, details)

    # scoping ----------------------------------------------------------------
    def staff_row(self) -> dict | None:
        return self.tenant.one("staff", "user_id=?", (self.uid,))

    def class_scope(self) -> list[int] | None:
        """None means every class; otherwise the class ids assigned to this teacher."""
        if self.can("classes.all"):
            return None
        staff = self.staff_row()
        if not staff:
            return []
        rows = self.tenant.q(
            "SELECT class_id FROM teacher_assignments WHERE institution_id=:iid AND staff_id=:s "
            "UNION SELECT id FROM classes WHERE institution_id=:iid AND class_teacher_id=:s",
            {"s": staff["id"]})
        return sorted({r["class_id"] for r in rows})

    def subject_scope(self, class_id: int) -> list[int] | None:
        """Subjects this user may enter marks for in a class (None = all)."""
        if self.can("classes.all") and self.can("exams.manage"):
            return None
        staff = self.staff_row()
        if not staff:
            return []
        rows = self.tenant.q(
            "SELECT subject_id FROM teacher_assignments WHERE institution_id=:iid "
            "AND staff_id=:s AND class_id=:c", {"s": staff["id"], "c": int(class_id)})
        if any(r["subject_id"] is None for r in rows):
            return None  # assigned to the whole class
        return [r["subject_id"] for r in rows]

    def check_class(self, class_id: int):
        scope = self.class_scope()
        if scope is not None and int(class_id) not in scope:
            raise PermissionDenied("This class is not assigned to you.")

    def portal_student_ids(self) -> list[int]:
        """Students a parent/student account may see (own record / linked children)."""
        T = self.tenant
        if self.user["role"] == "student" and self.user["linked_student_id"]:
            return [self.user["linked_student_id"]] if T.get("students", self.user["linked_student_id"]) else []
        if self.user["role"] == "parent" and self.user["linked_guardian_id"]:
            rows = T.all("student_guardians", "guardian_id=?", (self.user["linked_guardian_id"],))
            return [r["student_id"] for r in rows]
        return []
