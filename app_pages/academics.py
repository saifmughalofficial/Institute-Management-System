import sqlite3
from datetime import date

import pandas as pd
import streamlit as st

from ims import academics, people, session, ui, widgets

a = session.require("academics.manage")
T, S, P = a.tenant, a.settings, a.profile
ui.page_header(P["academics_page"], f"Academic years, {P['terms'].lower()}, {P['classes'].lower()}, "
                                    f"{P['subjects'].lower()} and teacher assignments", tips=[
    f"Work left to right: **year & {P['terms'].lower()}**, then {P['classes'].lower()}, {P['subjects'].lower()}, and finally teacher assignments.",
    "Mark one year and one term as **current**. Dashboards and reports use them by default.",
    f"A {P['subject'].lower()} linked to nothing is taught everywhere; link it to limit it.",
    "Teachers only see and mark the classes and subjects assigned to them."])


def remove(table, row_id, label):
    try:
        T.delete(table, row_id)
        a.log("deleted", table, row_id)
        session.flash(f"{label} removed.")
    except sqlite3.IntegrityError:
        st.error(f"{label} is in use by other records and cannot be removed. Deactivate it instead.")
        return
    st.rerun()


names = ["Years & " + P["terms"].lower()]
if P["faculties"]:
    names.append("Faculties")
if P["departments"]:
    names.append("Departments")
if P["programs_enabled"]:
    names.append(P["programs"])
names += [P["classes"], P["subjects"], "Teacher assignments"]
tabs = dict(zip(names, st.tabs(names)))

with tabs[names[0]]:
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("**Academic years**")
        years = T.all("academic_years", order="start_date DESC")
        if years:
            st.dataframe(pd.DataFrame(years)[["name", "start_date", "end_date", "is_current"]], hide_index=True,
                         column_config={"is_current": st.column_config.CheckboxColumn("Current")})
            yopts = {y["id"]: y["name"] for y in years}
            y = st.selectbox("Set current year", list(yopts), format_func=yopts.get, key="cur_y")
            if st.button("Make current", key="mk_y"):
                session.attempt(academics.set_current, a, "academic_years", y, success="Current year updated.", rerun=True)
        with st.form("add_year", clear_on_submit=True):
            n = st.text_input("Name", placeholder=f"{date.today().year}-{date.today().year + 1}")
            x1, x2 = st.columns(2)
            sd, ed = x1.date_input("Start", date(date.today().year, 8, 1)), x2.date_input("End", date(date.today().year + 1, 7, 31))
            if st.form_submit_button("Add year", icon=":material/add:"):
                try:
                    academics.check_dates(sd, ed)
                    if not n.strip():
                        raise ValueError("Name is required.")
                    T.insert("academic_years", name=n.strip(), start_date=sd.isoformat(), end_date=ed.isoformat(),
                             is_current=int(not years))
                    a.log("year_added", "academic_years")
                    session.flash("Year added.")
                    st.rerun()
                except (ValueError, sqlite3.IntegrityError) as exc:
                    st.error(str(exc) if isinstance(exc, ValueError) else "That year already exists.")
    with c2, st.container(border=True):
        st.markdown(f"**{P['terms']}**")
        terms = T.all("terms", order="start_date DESC")
        if terms:
            tdf = pd.DataFrame(terms)
            tdf["year"] = tdf["academic_year_id"].map({y["id"]: y["name"] for y in years})
            st.dataframe(tdf[["name", "year", "start_date", "end_date", "is_current"]], hide_index=True,
                         column_config={"is_current": st.column_config.CheckboxColumn("Current")})
            topts = {t["id"]: academics.term_label(T, t) for t in terms}
            t = st.selectbox(f"Set current {P['term'].lower()}", list(topts), format_func=topts.get, key="cur_t")
            if st.button("Make current", key="mk_t"):
                session.attempt(academics.set_current, a, "terms", t, success="Updated.", rerun=True)
        if years:
            with st.form("add_term", clear_on_submit=True):
                yopts = {y["id"]: y["name"] for y in years}
                yid = st.selectbox("Academic year", list(yopts), format_func=yopts.get)
                n = st.text_input("Name", placeholder="Term 1" if P["short"] == "School" else "Fall 2026")
                x1, x2 = st.columns(2)
                sd, ed = x1.date_input("Start"), x2.date_input("End", date.today().replace(month=12, day=31))
                if st.form_submit_button(f"Add {P['term'].lower()}", icon=":material/add:"):
                    try:
                        academics.check_dates(sd, ed)
                        if not n.strip():
                            raise ValueError("Name is required.")
                        T.insert("terms", academic_year_id=yid, name=n.strip(), start_date=sd.isoformat(),
                                 end_date=ed.isoformat(), is_current=int(not terms))
                        session.flash("Added.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        else:
            st.caption("Add an academic year first.")

if "Faculties" in tabs:
    with tabs["Faculties"]:
        rows = T.all("faculties", order="name")
        if rows:
            st.dataframe(pd.DataFrame(rows)[["name", "code"]], hide_index=True)
        with st.form("add_fac", clear_on_submit=True):
            x1, x2 = st.columns([3, 1])
            n, c = x1.text_input("Faculty name"), x2.text_input("Code")
            if st.form_submit_button("Add faculty", icon=":material/add:") and n.strip():
                try:
                    T.insert("faculties", name=n.strip(), code=c.strip())
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("That faculty already exists.")

if "Departments" in tabs:
    with tabs["Departments"]:
        facs = widgets.lookup(a, "faculties")
        rows = T.all("departments", order="name")
        if rows:
            df = pd.DataFrame(rows)
            df["faculty"] = df["faculty_id"].map(facs)
            st.dataframe(df[["name", "code"] + (["faculty"] if facs else [])], hide_index=True)
        with st.form("add_dept", clear_on_submit=True):
            x1, x2, x3 = st.columns([3, 1, 2])
            n, c = x1.text_input("Department name"), x2.text_input("Code")
            f = x3.selectbox("Faculty", list(facs), format_func=facs.get, index=None) if facs else None
            if st.form_submit_button("Add department", icon=":material/add:") and n.strip():
                try:
                    T.insert("departments", name=n.strip(), code=c.strip(), faculty_id=f)
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("That department already exists.")

if P["programs_enabled"]:
    with tabs[P["programs"]]:
        depts = widgets.lookup(a, "departments")
        rows = T.all("programs", order="name")
        if rows:
            df = pd.DataFrame(rows)
            df["department"] = df["department_id"].map(depts)
            st.dataframe(df[["name", "code", "level", "department", "duration_years", "total_semesters"]], hide_index=True)
        with st.form("add_prog", clear_on_submit=True):
            x1, x2, x3 = st.columns([3, 1, 2])
            n, c = x1.text_input(f"{P['program']} name"), x2.text_input("Code")
            d = x3.selectbox("Department", list(depts), format_func=depts.get, index=None)
            x1, x2, x3 = st.columns(3)
            lvl = x1.selectbox("Level", ["Undergraduate", "Graduate", "Postgraduate", "Diploma", "Intermediate", "Doctoral"])
            dur = x2.number_input("Duration (years)", 0.5, 8.0, 4.0, 0.5)
            sem = x3.number_input("Semesters", 1, 16, 8)
            if st.form_submit_button(f"Add {P['program'].lower()}", icon=":material/add:") and n.strip():
                try:
                    T.insert("programs", name=n.strip(), code=c.strip(), department_id=d, level=lvl,
                             duration_years=dur, total_semesters=int(sem))
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("That program already exists.")

with tabs[P["classes"]]:
    years = widgets.lookup(a, "academic_years")
    progs = widgets.lookup(a, "programs")
    staff = {s["id"]: s["full_name"] for s in T.all("staff", "employment_status='active'", order="full_name")}
    rows = T.q("""SELECT c.*, (SELECT COUNT(*) FROM students s WHERE s.class_id=c.id AND s.status='active') AS students
                  FROM classes c WHERE c.institution_id=:iid ORDER BY c.name, c.section""")
    if rows:
        df = pd.DataFrame(rows)
        df["year"] = df["academic_year_id"].map(years)
        df["program"] = df["program_id"].map(progs)
        df["class teacher"] = df["class_teacher_id"].map(staff)
        cols = ["name", "section", "year"] + (["program", "semester_no"] if P["programs_enabled"] else []) + \
               ["class teacher", "students", "capacity", "is_active"]
        st.dataframe(df[cols], hide_index=True, column_config={"is_active": st.column_config.CheckboxColumn("Active")})
    c1, c2 = st.columns(2)
    with c1, st.form("add_class", clear_on_submit=True):
        st.markdown(f"**Add {P['class'].lower()}**")
        x1, x2 = st.columns([2, 1])
        n = x1.text_input("Name", placeholder="Grade 6" if P["short"] == "School" else "BSCS Batch 2026")
        sec = x2.text_input(P["section"], "A")
        y = st.selectbox("Academic year", list(years), format_func=years.get,
                         index=list(years).index(academics.current_year(T)["id"]) if years else None)
        prog = sem = None
        if P["programs_enabled"]:
            x1, x2 = st.columns([2, 1])
            prog = x1.selectbox(P["program"], list(progs), format_func=progs.get, index=None)
            sem = x2.number_input(P["term"] + " no", 1, 16, 1)
        x1, x2 = st.columns(2)
        teacher = x1.selectbox("Class teacher / advisor", list(staff), format_func=staff.get, index=None)
        cap = x2.number_input("Capacity", 1, 500, 40)
        if st.form_submit_button("Add", type="primary", icon=":material/add:") and n.strip():
            T.insert("classes", name=n.strip(), section=sec.strip(), academic_year_id=y, program_id=prog,
                     semester_no=int(sem) if sem else None, class_teacher_id=teacher, capacity=int(cap))
            a.log("class_added", "classes")
            session.flash("Added.")
            st.rerun()
    if rows:
        with c2, st.container(border=True):
            st.markdown(f"**Edit {P['class'].lower()}**")
            copts = {r["id"]: people.class_label(r) for r in rows}
            cid = st.selectbox("Choose", list(copts), format_func=copts.get, key="edit_cls")
            c = T.get("classes", cid)
            teacher = st.selectbox("Class teacher", [None] + list(staff), format_func=lambda k: "—" if k is None else staff[k],
                                   index=([None] + list(staff)).index(c["class_teacher_id"]) if c["class_teacher_id"] in staff else 0,
                                   key=f"ct_{cid}")
            cap = st.number_input("Capacity", 1, 500, int(c["capacity"] or 40), key=f"cap_{cid}")
            active = st.toggle("Active", bool(c["is_active"]), key=f"act_{cid}")
            b = st.container(horizontal=True)
            if b.button("Save", key="save_cls", icon=":material/save:"):
                T.update("classes", cid, class_teacher_id=teacher, capacity=int(cap), is_active=int(active))
                session.flash("Saved.")
                st.rerun()
            if b.button("Delete", key="del_cls", icon=":material/delete:"):
                remove("classes", cid, copts[cid])

with tabs[P["subjects"]]:
    progs = widgets.lookup(a, "programs")
    copts = people.class_options(a, only_scope=False)
    rows = T.all("subjects", order="name")
    if rows:
        df = pd.DataFrame(rows)
        df["program"] = df["program_id"].map(progs)
        df["class"] = df["class_id"].map(copts)
        cols = ["name", "code"] + (["credit_hours"] if P["credit_hours"] else []) + \
               (["program", "semester_no"] if P["programs_enabled"] else []) + ["class", "max_marks", "is_elective"]
        st.dataframe(df[cols], hide_index=True, column_config={"is_elective": st.column_config.CheckboxColumn("Elective")})
    st.caption(f"A {P['subject'].lower()} linked to nothing is taught in every {P['class'].lower()}; link it to a "
               f"{(P['program'] or P['class']).lower()} to limit it.")
    with st.form("add_sub", clear_on_submit=True):
        x1, x2, x3 = st.columns([3, 1, 1])
        n, code = x1.text_input("Name"), x2.text_input("Code")
        mx = x3.number_input("Max marks", 1, 1000, 100)
        x1, x2, x3, x4 = st.columns(4)
        cr = x1.number_input("Credit hours", 0.0, 12.0, 3.0 if P["credit_hours"] else 1.0, 0.5) if P["credit_hours"] else 1.0
        prog = x2.selectbox(P["program"], list(progs), format_func=progs.get, index=None) if P["programs_enabled"] else None
        sem = x3.number_input(P["term"] + " no", 0, 16, 0) if P["programs_enabled"] else 0
        cls = x4.selectbox(f"Only for {P['class'].lower()}", list(copts), format_func=copts.get, index=None)
        elective = st.checkbox("Elective")
        if st.form_submit_button(f"Add {P['subject'].lower()}", type="primary", icon=":material/add:") and n.strip():
            try:
                T.insert("subjects", name=n.strip(), code=code.strip() or None, max_marks=mx, credit_hours=cr,
                         program_id=prog, semester_no=int(sem) or None, class_id=cls, is_elective=int(elective))
                session.flash("Added.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("That code is already used.")

with tabs["Teacher assignments"]:
    staff = {s["id"]: s["full_name"] for s in T.all("staff", "employment_status='active'", order="full_name")}
    copts = people.class_options(a, only_scope=False)
    rows = T.q("""SELECT t.id, s.full_name AS teacher, c.name || IFNULL(' – ' || NULLIF(c.section,''),'') AS cls,
                  IFNULL(sub.name, 'Whole class') AS subject FROM teacher_assignments t JOIN staff s ON s.id=t.staff_id
                  JOIN classes c ON c.id=t.class_id LEFT JOIN subjects sub ON sub.id=t.subject_id
                  WHERE t.institution_id=:iid ORDER BY c.name, sub.name""")
    st.caption("Teachers can only take attendance and enter marks for the classes and subjects assigned here.")
    if rows:
        st.dataframe(pd.DataFrame(rows).drop(columns="id"), hide_index=True)
    if staff and copts:
        x1, x2, x3 = st.columns(3)
        sid = x1.selectbox(P["staff"], list(staff), format_func=staff.get, key="as_t")
        cid = x2.selectbox(P["class"], list(copts), format_func=copts.get, key="as_c")
        subs = {s["id"]: s["name"] for s in academics.subjects_for_class(T, T.get("classes", cid))}
        sub = x3.selectbox(P["subject"], [None] + list(subs), format_func=lambda k: "Whole class" if k is None else subs[k], key="as_s")
        if st.button("Assign", type="primary", icon=":material/link:"):
            session.attempt(people.assign_teacher, a, sid, cid, sub, success="Assigned.", rerun=True)
        if rows:
            ropts = {r["id"]: f"{r['teacher']} · {r['cls']} · {r['subject']}" for r in rows}
            rid = st.selectbox("Remove assignment", list(ropts), format_func=ropts.get, index=None)
            if rid and st.button("Remove", icon=":material/link_off:"):
                remove("teacher_assignments", rid, "Assignment")
