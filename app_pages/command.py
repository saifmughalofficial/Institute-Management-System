"""Command center: type a command to see everything about one class, department, program, student, staff member or subject."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ims import academics, attendance as att, exams, fees, people, session, ui

a = session.require("dashboard.view")
T, S, P = a.tenant, a.settings, a.profile
scope = a.class_scope()
ui.page_header("Command center", "Type a command to see everything about any class, department, program, student, staff member or subject", tips=[
    "Type a command and press **Enter**, e.g. `class Grade 6 A` or `department Computer Science`.",
    "Partial words work: `class 6` finds every grade 6 section.",
    "Just type a name to search everything.",
    "Press **Ctrl+K** anywhere to jump here from the sidebar search."])

KINDS = {
    "class": ["class", "cls", "cohort", "batch", "grade", "section"],
    "department": ["department", "dept", "dep"],
    "faculty": ["faculty"],
    "program": ["program", "programme", "prog", "degree"],
    "student": ["student", "std", "stu"],
    "staff": ["staff", "teacher", "lecturer", "faculty-member", "emp"],
    "subject": ["subject", "course", "sub"],
    "list": ["list", "all", "show"],
}
EXAMPLES = ["list classes", "list departments", "class Grade 6 A", "department Computer Science", "student Ayesha",
            "staff Rabia", "subject Mathematics", "program BS Computer Science", "help"]

st.caption("Examples: " + " · ".join(f"`{e}`" for e in EXAMPLES))
def _chip():
    if st.session_state.get("cmd_chip"):
        st.session_state["cmd_text"] = st.session_state["cmd_chip"]


st.pills("Quick commands", ["list classes", "list departments", "list programs", "list staff", "list subjects", "help"],
         key="cmd_chip", label_visibility="collapsed", on_change=_chip)
cmd = st.text_input("Command", placeholder="e.g. class Grade 6 A   ·   department Computer Science   ·   student 0012",
                    key="cmd_text", icon=":material/terminal:")


def parse(text: str):
    words = text.strip().split()
    if not words:
        return None, ""
    head = words[0].lower()
    for kind, aliases in KINDS.items():
        if head in aliases:
            return kind, " ".join(words[1:]).strip()
    if head == "help":
        return "help", ""
    return "search", text.strip()


def class_rows():
    rows = T.all("classes", order="name, section")
    return [c for c in rows if scope is None or c["id"] in scope]


def like(text, *values):
    t = text.lower().replace("–", " ").replace("-", " ")
    return all(w in " ".join(str(v or "") for v in values).lower().replace("-", " ") for w in t.split())


def pick(options: dict, label: str):
    if not options:
        st.warning(f"No {label} matches that command.", icon=":material/search_off:")
        return None
    if len(options) == 1:
        return next(iter(options))
    return st.selectbox(f"{len(options)} {label + ('es' if label.endswith('s') else 's')} match. Choose one", list(options), format_func=options.get, key=f"pick_{label}")


def kpis(items):
    row = st.container(horizontal=True)
    for label, value in items:
        row.metric(label, value, width="stretch")


start90 = (date.today() - timedelta(days=90)).isoformat()


def show_class(c):
    st.markdown(f"## {people.class_label(c)}")
    studs = T.all("students", "class_id=? AND status='active'", (c["id"],), order="first_name")
    teacher = T.get("staff", c["class_teacher_id"])
    pct = att.percentages(T, start90, date.today().isoformat(), class_id=c["id"])
    avg = pct["percent"].mean() if not pct.empty else None
    items = [("Students", len(studs)), ("Class teacher", teacher["full_name"] if teacher else "—"),
             ("Attendance (90d)", f"{avg:.1f}%" if avg == avg and avg is not None else "—")]
    if a.can("fees.view"):
        invs = [i for i in fees.invoices(T, "st.class_id=:c AND i.status='issued'", {"c": c["id"]})]
        items.append(("Fee balance", ui.money(sum(i["balance"] for i in invs), S)))
    kpis(items)
    t = st.tabs(["Students", P["subjects"], "Timetable", "Attendance", "Results"])
    with t[0]:
        st.dataframe(pd.DataFrame([{"Admission no": s["admission_no"], "Student": people.full_name(s), "Gender": s["gender"],
                                    "Phone": s["phone"]} for s in studs]), hide_index=True)
    with t[1]:
        subs = academics.subjects_for_class(T, c)
        asg = {r["subject_id"]: r["full_name"] for r in T.q(
            "SELECT t.subject_id, s.full_name FROM teacher_assignments t JOIN staff s ON s.id=t.staff_id "
            "WHERE t.institution_id=:iid AND t.class_id=:c", {"c": c["id"]})}
        st.dataframe(pd.DataFrame([{"Code": s["code"], P["subject"]: s["name"], "Credits": s["credit_hours"],
                                    "Teacher": asg.get(s["id"], "—")} for s in subs]), hide_index=True)
    with t[2]:
        rows = T.q("""SELECT t.day, t.period, IFNULL(s.name,'—') || IFNULL(' · ' || st.full_name,'') AS cell FROM timetable t
                      LEFT JOIN subjects s ON s.id=t.subject_id LEFT JOIN staff st ON st.id=t.staff_id
                      WHERE t.institution_id=:iid AND t.class_id=:c""", {"c": c["id"]})
        if rows:
            df = pd.DataFrame(rows).pivot_table(index="period", columns="day", values="cell", aggfunc="first")
            st.dataframe(df.reindex(columns=[d for d in att.DAYS if d in df.columns]).fillna(""), width="stretch")
        else:
            st.caption("No timetable.")
    with t[3]:
        if not pct.empty:
            st.dataframe(pct[["admission_no", "student", "attended", "absent", "percent"]], hide_index=True,
                         column_config={"percent": st.column_config.ProgressColumn("%", min_value=0, max_value=100, format="%.1f")})
    with t[4]:
        ex = T.q("SELECT DISTINCT e.id, e.name FROM exams e JOIN marksheets m ON m.exam_id=e.id WHERE e.institution_id=:iid "
                 "AND m.class_id=:c ORDER BY e.id DESC", {"c": c["id"]})
        if ex:
            eid = st.selectbox("Exam", [e["id"] for e in ex], format_func=lambda i: next(e["name"] for e in ex if e["id"] == i), key="cmd_exam")
            sheet = exams.class_result_sheet(T, S, eid, c["id"], published_only=not a.can("exams.manage", "results.review"))
            st.dataframe(sheet.drop(columns=["student_id"], errors="ignore"), hide_index=True)
        else:
            st.caption("No results yet.")


def show_department(d):
    st.markdown(f"## {d['name']}" + (f" ({d['code']})" if d["code"] else ""))
    progs = T.all("programs", "department_id=?", (d["id"],), order="name")
    staff = T.all("staff", "department_id=?", (d["id"],), order="full_name")
    pids = [p_["id"] for p_ in progs] or [0]
    classes = [c for c in T.all("classes", f"program_id IN ({','.join(map(str, pids))})") if scope is None or c["id"] in scope]
    cids = [c["id"] for c in classes] or [0]
    n_students = T.count("students", f"status='active' AND class_id IN ({','.join(map(str, cids))})")
    fac = T.get("faculties", d["faculty_id"])
    kpis([("Programs", len(progs)), (P["classes"], len(classes)), ("Students", n_students), ("Staff", len(staff))]
         + ([("Faculty", fac["name"])] if fac else []))
    t = st.tabs([P["programs"] or "Programs", P["classes"], "Staff", P["subjects"]])
    with t[0]:
        st.dataframe(pd.DataFrame(progs)[["name", "code", "level", "duration_years", "total_semesters"]] if progs else pd.DataFrame(), hide_index=True)
    with t[1]:
        st.dataframe(pd.DataFrame([{P["class"]: people.class_label(c), "Students": T.count("students", "class_id=? AND status='active'", (c["id"],))}
                                   for c in classes]), hide_index=True)
    with t[2]:
        st.dataframe(pd.DataFrame([{"Staff no": s["staff_no"], "Name": s["full_name"], "Designation": s["designation"],
                                    "Phone": s["phone"]} for s in staff]), hide_index=True)
    with t[3]:
        subs = T.all("subjects", f"program_id IN ({','.join(map(str, pids))})", order="name")
        st.dataframe(pd.DataFrame([{"Code": s["code"], "Name": s["name"], "Credits": s["credit_hours"], "Semester": s["semester_no"]}
                                   for s in subs]), hide_index=True)


def show_program(pr):
    st.markdown(f"## {pr['name']}")
    classes = [c for c in T.all("classes", "program_id=?", (pr["id"],)) if scope is None or c["id"] in scope]
    subs = T.all("subjects", "program_id=?", (pr["id"],), order="semester_no, name")
    kpis([("Level", pr["level"] or "—"), ("Duration", f"{pr['duration_years'] or 0:g} years"),
          (P["classes"], len(classes)), (P["subjects"], len(subs)),
          ("Students", T.count("students", "program_id=? AND status='active'", (pr["id"],)))])
    st.dataframe(pd.DataFrame([{"Semester": s["semester_no"], "Code": s["code"], P["subject"]: s["name"], "Credits": s["credit_hours"]}
                               for s in subs]), hide_index=True)


def show_student(s):
    cls = T.get("classes", s["class_id"])
    st.markdown(f"## {people.full_name(s)}  {ui.badge_md(s['status'])}")
    pct = att.percentages(T, start90, date.today().isoformat(), student_ids=[s["id"]])
    ap = pct.iloc[0]["percent"] if not pct.empty else None
    items = [("Admission no", s["admission_no"]), (P["class"], people.class_label(cls)),
             ("Attendance (90d)", f"{ap:.1f}%" if ap == ap and ap is not None else "—")]
    if a.can("fees.view"):
        items.append(("Fee balance", ui.money(sum(i["balance"] for i in fees.invoices(T, "i.student_id=:s AND i.status='issued'", {"s": s["id"]})), S)))
    kpis(items)
    g = T.q("SELECT g.name, g.phone, sg.relationship FROM student_guardians sg JOIN guardians g ON g.id=sg.guardian_id "
            "WHERE sg.institution_id=:iid AND sg.student_id=:s", {"s": s["id"]})
    st.markdown("**Guardians:** " + (", ".join(f"{x['name']} ({x['relationship']}, {x['phone'] or '—'})" for x in g) or "—"))
    tr = exams.transcript(T, S, s["id"])
    rows = [{P["term"]: t["term"]["name"], "Result": t["report"]["result"], "%": t["report"]["percent"], "GPA": t["report"]["gpa"]}
            for t in tr["terms"]]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.page_link("app_pages/students.py", label="Open full student profile", icon=":material/open_in_new:")


def show_staff(s):
    st.markdown(f"## {s['full_name']}")
    asg = T.q("""SELECT c.name || IFNULL(' – ' || NULLIF(c.section,''),'') AS cls, IFNULL(sub.name,'Whole class') AS subject
                 FROM teacher_assignments t JOIN classes c ON c.id=t.class_id LEFT JOIN subjects sub ON sub.id=t.subject_id
                 WHERE t.institution_id=:iid AND t.staff_id=:s""", {"s": s["id"]})
    dept = T.get("departments", s["department_id"])
    kpis([("Staff no", s["staff_no"]), ("Designation", s["designation"] or "—"), ("Department", dept["name"] if dept else "—"),
          ("Weekly periods", T.count("timetable", "staff_id=?", (s["id"],)))])
    st.dataframe(pd.DataFrame(asg), hide_index=True) if asg else st.caption("No assignments.")


def show_subject(sub):
    st.markdown(f"## {sub['name']}" + (f" ({sub['code']})" if sub["code"] else ""))
    asg = T.q("""SELECT c.name || IFNULL(' – ' || NULLIF(c.section,''),'') AS cls, s.full_name AS teacher FROM teacher_assignments t
                 JOIN classes c ON c.id=t.class_id JOIN staff s ON s.id=t.staff_id
                 WHERE t.institution_id=:iid AND t.subject_id=:x""", {"x": sub["id"]})
    avg = T.scalar("SELECT ROUND(AVG(100.0*IFNULL(r.obtained_marks,0)/r.max_marks),1) AS v FROM results r JOIN marksheets m "
                   "ON m.id=r.marksheet_id WHERE r.institution_id=:iid AND r.subject_id=:x AND m.status='published'", {"x": sub["id"]})
    kpis([("Credit hours", f"{sub['credit_hours']:g}"), ("Max marks", f"{sub['max_marks']:g}"),
          ("Taught in", len(asg)), ("Average % (published)", avg if avg is not None else "—")])
    st.dataframe(pd.DataFrame(asg), hide_index=True) if asg else st.caption("Not assigned yet.")


kind, arg = parse(cmd)
if kind is None:
    st.info("Type a command above, or tap a quick command.", icon=":material/keyboard:")
elif kind == "help":
    st.markdown("""
| Command | Shows |
|---|---|
| `list classes` / `list departments` / `list programs` / `list staff` / `list subjects` | Every item with counts |
| `class <name or section>` | Students, subjects & teachers, timetable, attendance, results, fees |
| `department <name or code>` | Programs, classes, staff, courses, student count |
| `program <name>` | Semester-wise courses, classes, students |
| `student <name or admission no>` | Profile, guardians, attendance, fees, results by term |
| `staff <name or staff no>` | Assignments, department, weekly load |
| `subject <name or code>` | Where it is taught, by whom, average result |
| anything else | Searches all of the above |
""")
elif kind == "list":
    what = arg.lower().rstrip("s")
    if what in ("class", "cohort", "batche", "batch", "grade", "section", ""):
        df = pd.DataFrame([{P["class"]: people.class_label(c), "Students": T.count("students", "class_id=? AND status='active'", (c["id"],)),
                            "Teacher": (T.get("staff", c["class_teacher_id"]) or {}).get("full_name", "—")} for c in class_rows()])
    elif what in ("department", "dept"):
        df = pd.DataFrame([{"Department": d["name"], "Code": d["code"], "Programs": T.count("programs", "department_id=?", (d["id"],)),
                            "Staff": T.count("staff", "department_id=?", (d["id"],))} for d in T.all("departments", order="name")])
    elif what in ("program", "programme"):
        df = pd.DataFrame([{"Program": x["name"], "Level": x["level"], "Students": T.count("students", "program_id=? AND status='active'", (x["id"],))}
                           for x in T.all("programs", order="name")])
    elif what in ("staff", "teacher"):
        df = pd.DataFrame([{"Staff no": s["staff_no"], "Name": s["full_name"], "Designation": s["designation"]}
                           for s in T.all("staff", "employment_status='active'", order="full_name")])
    elif what in ("subject", "course"):
        df = pd.DataFrame([{"Code": s["code"], "Name": s["name"], "Credits": s["credit_hours"]} for s in T.all("subjects", order="name")])
    else:
        df = pd.DataFrame()
        st.warning("Try: list classes, list departments, list programs, list staff or list subjects.")
    if not df.empty:
        st.dataframe(df, hide_index=True)
elif kind == "class":
    cid = pick({c["id"]: people.class_label(c) for c in class_rows() if like(arg, c["name"], c["section"])}, "class")
    if cid:
        show_class(T.get("classes", cid))
elif kind in ("department", "faculty"):
    if kind == "faculty" and P["faculties"]:
        fid = pick({f["id"]: f["name"] for f in T.all("faculties") if like(arg, f["name"], f["code"])}, "faculty")
        if fid:
            for d in T.all("departments", "faculty_id=?", (fid,)):
                with st.container(border=True):
                    show_department(d)
    else:
        did = pick({d["id"]: d["name"] for d in T.all("departments") if like(arg, d["name"], d["code"])}, "department")
        if did:
            show_department(T.get("departments", did))
elif kind == "program":
    pid = pick({x["id"]: x["name"] for x in T.all("programs") if like(arg, x["name"], x["code"])}, "program")
    if pid:
        show_program(T.get("programs", pid))
elif kind == "student":
    if not a.can("students.view"):
        st.error("You do not have permission to view students.")
    else:
        rows = [s for s in T.all("students") if (scope is None or s["class_id"] in scope)
                and like(arg, s["first_name"], s["last_name"], s["admission_no"])]
        sid = pick({s["id"]: f"{people.full_name(s)} · {s['admission_no']}" for s in rows[:200]}, "student")
        if sid:
            show_student(T.get("students", sid))
elif kind == "staff":
    sid = pick({s["id"]: f"{s['full_name']} · {s['staff_no']}" for s in T.all("staff") if like(arg, s["full_name"], s["staff_no"])}, "staff member")
    if sid:
        show_staff(T.get("staff", sid))
elif kind == "subject":
    xid = pick({x["id"]: f"{x['name']} {x['code'] or ''}" for x in T.all("subjects") if like(arg, x["name"], x["code"])}, "subject")
    if xid:
        show_subject(T.get("subjects", xid))
else:  # free search across everything
    hits = []
    hits += [("Class", people.class_label(c), f"class {c['name']} {c['section']}") for c in class_rows() if like(arg, c["name"], c["section"])]
    hits += [("Department", d["name"], f"department {d['name']}") for d in T.all("departments") if like(arg, d["name"], d["code"])]
    hits += [("Program", x["name"], f"program {x['name']}") for x in T.all("programs") if like(arg, x["name"], x["code"])]
    hits += [("Staff", s["full_name"], f"staff {s['full_name']}") for s in T.all("staff") if like(arg, s["full_name"], s["staff_no"])]
    hits += [(P["subject"], x["name"], f"subject {x['name']}") for x in T.all("subjects") if like(arg, x["name"], x["code"])]
    if a.can("students.view"):
        hits += [("Student", people.full_name(s), f"student {s['admission_no']}") for s in T.all("students")
                 if (scope is None or s["class_id"] in scope) and like(arg, s["first_name"], s["last_name"], s["admission_no"])][:50]
    if hits:
        st.markdown(f"**{len(hits)} result(s).** Copy a command below to open one:")
        st.dataframe(pd.DataFrame(hits, columns=["Type", "Name", "Command"]), hide_index=True)
    else:
        st.warning("Nothing found. Type `help` to see the commands.", icon=":material/search_off:")
