"""Reusable Streamlit pickers and export buttons (all tenant- and scope-aware)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import academics, exports, pdf, people
from .actor import Actor


def student_options(actor: Actor, statuses=("active",), class_id=None, scoped=True) -> dict[int, str]:
    T = actor.tenant
    where, params = [], []
    if statuses:
        where.append(f"status IN ({','.join('?' * len(statuses))})")
        params += list(statuses)
    if class_id:
        where.append("class_id=?")
        params.append(int(class_id))
    scope = actor.class_scope() if scoped else None
    if scope is not None:
        where.append(f"class_id IN ({','.join(str(i) for i in scope) or '0'})")
    rows = T.all("students", " AND ".join(where), tuple(params), order="first_name, last_name")
    return {r["id"]: f"{people.full_name(r)} · {r['admission_no']}" for r in rows}


def pick_student(actor: Actor, key: str, label: str = "Student", statuses=("active",), class_id=None,
                 scoped=True) -> dict | None:
    opts = student_options(actor, statuses, class_id, scoped)
    if not opts:
        st.info("No matching students yet.", icon=":material/info:")
        return None
    sid = st.selectbox(label, list(opts), format_func=opts.get, key=key, index=None,
                       placeholder="Search by name or admission number")
    return actor.tenant.get("students", sid) if sid else None


def pick_class(actor: Actor, key: str, label: str | None = None, scoped=True, allow_none=False,
               none_label="All") -> int | None:
    opts = people.class_options(actor, only_scope=scoped)
    label = label or actor.profile["class"]
    if not opts:
        st.info(f"No {actor.profile['classes'].lower()} available. Create them in "
                f"{actor.profile['academics_page']}.", icon=":material/info:")
        return None
    keys = ([None] if allow_none else []) + list(opts)
    return st.selectbox(label, keys, format_func=lambda k: none_label if k is None else opts[k], key=key)


def pick_term(actor: Actor, key: str, label: str | None = None) -> dict | None:
    T = actor.tenant
    terms = T.all("terms", order="start_date DESC")
    if not terms:
        st.info(f"No {actor.profile['terms'].lower()} yet. Add them in {actor.profile['academics_page']}.",
                icon=":material/info:")
        return None
    cur = academics.current_term(T)
    ids = [t["id"] for t in terms]
    tid = st.selectbox(label or actor.profile["term"], ids, key=key,
                       index=ids.index(cur["id"]) if cur else 0,
                       format_func=lambda i: academics.term_label(T, T.get("terms", i)))
    return T.get("terms", tid)


def pick_exam(actor: Actor, key: str, term_id: int | None = None, label="Exam") -> dict | None:
    T = actor.tenant
    rows = T.all("exams", "term_id=?", (term_id,), order="start_date DESC, id DESC") if term_id \
        else T.all("exams", order="id DESC")
    if not rows:
        st.info("No exams yet.", icon=":material/info:")
        return None
    eid = st.selectbox(label, [r["id"] for r in rows], key=key,
                       format_func=lambda i: next(f"{r['name']} ({r['exam_type']}, {r['weightage']:g}%)"
                                                  for r in rows if r["id"] == i))
    return T.get("exams", eid)


def export_buttons(actor: Actor, title: str, df: pd.DataFrame, key: str, perm: str = "reports.export"):
    """CSV / Excel / PDF downloads with the institution heading. Generation is
    deferred until click, and every export is written to the audit log."""
    if df is None or df.empty:
        return
    if perm and not actor.can(perm):
        st.caption(":material/lock: Exporting needs the export permission.")
        return
    inst, settings = actor.inst, actor.settings
    name = exports.safe_filename(f"{inst['name']}_{title}")
    frame = df.copy()

    def make(kind):
        def build():
            actor.log("export", "report", None, {"title": title, "format": kind, "rows": len(frame)})
            if kind == "csv":
                return exports.csv_bytes(inst, title, frame)
            if kind == "xlsx":
                return exports.xlsx_bytes(inst, title, frame)
            return pdf.table_pdf(inst, settings, title, frame)
        return build

    row = st.container(horizontal=True)
    row.download_button("CSV", make("csv"), f"{name}.csv", "text/csv", key=f"{key}_csv",
                        icon=":material/table:", on_click="ignore")
    row.download_button("Excel", make("xlsx"), f"{name}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"{key}_xlsx", icon=":material/grid_on:", on_click="ignore")
    row.download_button("PDF", make("pdf"), f"{name}.pdf", "application/pdf", key=f"{key}_pdf",
                        icon=":material/picture_as_pdf:", on_click="ignore")


def empty(message: str, icon: str = ":material/inbox:"):
    st.info(message, icon=icon)


def lookup(actor: Actor, table: str, label_col: str = "name") -> dict[int, str]:
    return {r["id"]: r[label_col] for r in actor.tenant.all(table, order=label_col)}
