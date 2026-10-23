"""Academic structure helpers shared by pages and services."""
from __future__ import annotations

from . import db
from .accounts import ValidationError
from .actor import Actor


def current_year(T) -> dict | None:
    return T.one("academic_years", "is_current=1") or (T.all("academic_years", order="start_date DESC") or [None])[0]


def current_term(T) -> dict | None:
    return T.one("terms", "is_current=1") or (T.all("terms", order="start_date DESC") or [None])[0]


def subjects_for_class(T, cls: dict) -> list[dict]:
    """Subjects taught in a class: linked to the class directly, to its program
    (and semester, if set) or general subjects linked to nothing."""
    return T.q("""
        SELECT * FROM subjects WHERE institution_id=:iid AND (
            class_id=:c
            OR (class_id IS NULL AND program_id IS NULL)
            OR (class_id IS NULL AND program_id=:p AND (semester_no IS NULL OR :sem IS NULL OR semester_no=:sem))
        ) ORDER BY name
    """, {"c": cls["id"], "p": cls.get("program_id") or -1, "sem": cls.get("semester_no")})


def set_current(actor: Actor, table: str, row_id: int):
    actor.require("academics.manage")
    if table not in ("academic_years", "terms"):
        raise ValidationError("Invalid table.")
    T = actor.tenant
    T.require(table, row_id)
    with db.transaction():
        db.execute(f"UPDATE {table} SET is_current=0 WHERE institution_id=?", (actor.iid,))
        T.update(table, row_id, is_current=1)
        actor.log("set_current", table, row_id)


def check_dates(start, end):
    if end <= start:
        raise ValidationError("The end date must be after the start date.")


def term_label(T, term: dict | None) -> str:
    if not term:
        return "—"
    y = T.get("academic_years", term["academic_year_id"])
    return f"{term['name']} ({y['name']})" if y else term["name"]
