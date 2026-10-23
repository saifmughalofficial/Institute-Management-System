"""Fictional demo data so a new workspace can be explored immediately.

All names are invented. Demo logins share the password DEMO_PASSWORD and are
shown once after creation.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta

from . import academics, attendance, db, exams, fees, people
from .accounts import create_user
from .actor import Actor
from .profiles import default_settings, load_settings

DEMO_PASSWORD = "Demo@2026"
DEMO_PROFILE = {"address": "12 Knowledge Avenue, Model Town", "phone": "+92 300 0000000",
                "email": "info@example.edu", "motto": "Learn · Lead · Serve"}

FIRST = ["Ayesha", "Hamza", "Zainab", "Bilal", "Fatima", "Usman", "Maryam", "Ali", "Hira", "Saad",
         "Noor", "Ahmed", "Iqra", "Hassan", "Sana", "Omar", "Laiba", "Danish", "Aiman", "Rayyan",
         "Mahnoor", "Taha", "Eman", "Yusuf", "Alina", "Zaid", "Areeba", "Fahad", "Khadija", "Musa",
         "Amna", "Ibrahim", "Rida", "Shayan", "Anaya", "Hadi", "Minahil", "Arham", "Zoya", "Faris"]
LAST = ["Qureshi", "Malik", "Siddiqui", "Chaudhry", "Rehman", "Javed", "Iqbal", "Raza", "Butt",
        "Hashmi", "Farooq", "Aslam", "Mirza", "Sheikh", "Anwar", "Kazmi", "Baig", "Naqvi", "Abbasi", "Riaz"]
STAFF = ["Sadia Nawaz", "Kamran Akhtar", "Rabia Saleem", "Tariq Mehmood", "Nadia Hussain",
         "Faisal Karim", "Saima Tahir", "Waqas Ahmed", "Huma Zafar", "Imran Latif", "Asma Rauf"]


def _weekdays_back(n: int, working: list[str]) -> list[date]:
    out, d = [], date.today()
    while len(out) < n:
        if attendance.DAYS[d.weekday()] in working:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def has_demo_data(inst: dict) -> bool:
    return bool(load_settings(inst).get("demo_data"))


def clear_institution_data(actor: Actor) -> int:
    """Remove every record of the institution (students, staff, fees, results, demo logins, uploads…)
    while keeping the institution profile, logo, settings and the owner account. Owner only."""
    from pathlib import Path

    from .backup import TABLE_ORDER
    if not actor.user["is_owner"]:
        raise PermissionError("Only the institution owner can clear all data.")
    iid = actor.iid
    keep = {"users", "audit_log"}
    removed = 0
    with db.transaction() as con:
        con.execute("PRAGMA defer_foreign_keys=ON")
        for t in reversed(TABLE_ORDER):
            if t in keep:
                continue
            removed += con.execute(f"DELETE FROM {t} WHERE institution_id=?", (iid,)).rowcount
        others = [r["id"] for r in db.query("SELECT id FROM users WHERE institution_id=? AND is_owner=0", (iid,))]
        if others:
            marks = ",".join("?" * len(others))
            con.execute(f"UPDATE audit_log SET user_id=NULL WHERE user_id IN ({marks})", others)
            removed += con.execute(f"DELETE FROM users WHERE id IN ({marks})", others).rowcount
        con.execute("UPDATE users SET linked_student_id=NULL, linked_guardian_id=NULL WHERE institution_id=?", (iid,))
        s = load_settings(actor.inst)
        s["demo_data"] = False
        # Undo the profile/settings values the demo seeder filled in.
        defaults = default_settings(actor.inst["institution_type"])
        s["modules"], s["late_fee_amount"] = defaults["modules"], defaults["late_fee_amount"]
        con.execute("UPDATE institutions SET settings_json=? WHERE id=?", (json.dumps(s), iid))
        for col, val in DEMO_PROFILE.items():
            con.execute(f"UPDATE institutions SET {col}=NULL WHERE id=? AND {col}=?", (iid, val))
    for kind in ("uploads", "photos"):
        folder = Path(db.media_root()) / "institutions" / str(iid) / kind
        if folder.exists():
            for f in folder.iterdir():
                if f.is_file():
                    f.unlink()
    actor.log("institution_data_cleared", "institution", iid, {"rows_removed": removed})
    return removed


def instant_demo(kind: str, session_key: str) -> tuple[int, str, str, list]:
    """One click: create a fully seeded demo workspace and return (owner uid, username, password, demo logins)."""
    import secrets
    from .accounts import create_workspace
    tag = secrets.token_hex(2).upper()
    username = f"demo_{kind}_{tag.lower()}"
    password = f"Demo-{secrets.token_hex(3)}9"
    names = {"school": "Sunrise Demo School", "college": "Crescent Demo College", "university": "Horizon Demo University"}
    _, uid = create_workspace(institution_type=kind, name=f"{names[kind]} {tag}", logo_png=None,
                              admin_name="Demo Administrator", username=username, email="", password=password,
                              session_key=session_key)
    return uid, username, password, seed(uid)


def seed(owner_uid: int, rng_seed: int = 7) -> list[tuple[str, str, str]]:
    """Fill the owner's institution with demo data. Returns demo logins."""
    rnd = random.Random(rng_seed)
    a = Actor.load(owner_uid)
    T = a.tenant
    kind = a.inst["institution_type"]
    with db.transaction():
        # Enable every optional module so the demo shows everything.
        s = load_settings(a.inst)
        s["modules"] = {k: True for k in s["modules"]}
        s["late_fee_amount"] = 500.0
        s["demo_data"] = True
        db.execute("UPDATE institutions SET settings_json=?, address=?, phone=?, email=?, motto=? WHERE id=?",
                   (json.dumps(s), DEMO_PROFILE["address"], DEMO_PROFILE["phone"], DEMO_PROFILE["email"],
                    DEMO_PROFILE["motto"], a.iid))
        a = Actor.load(owner_uid)

        today = date.today()
        y0 = today.year if today.month >= 8 else today.year - 1
        prev_year = T.insert("academic_years", name=f"{y0 - 1}-{y0}", start_date=f"{y0 - 1}-08-01",
                             end_date=f"{y0}-07-31", is_current=0)
        year = T.insert("academic_years", name=f"{y0}-{y0 + 1}", start_date=f"{y0}-08-01",
                        end_date=f"{y0 + 1}-07-31", is_current=1)
        if kind == "school":
            t_names = [("Term 2", f"{y0}-01-05", f"{y0}-07-31", prev_year), ("Term 1", f"{y0}-08-01", f"{y0}-12-20", year),
                       ("Term 2", f"{y0 + 1}-01-05", f"{y0 + 1}-07-31", year)]
        else:
            t_names = [("Spring", f"{y0}-01-15", f"{y0}-06-15", prev_year), ("Fall", f"{y0}-08-15", f"{y0}-12-31", year),
                       ("Spring", f"{y0 + 1}-01-15", f"{y0 + 1}-06-15", year)]
        term_ids = [T.insert("terms", academic_year_id=yid, name=f"{n} {st[:4]}" if kind != "school" else n,
                             start_date=st, end_date=en, is_current=int(i == 1))
                    for i, (n, st, en, yid) in enumerate(t_names)]
        prev_term, cur_term = term_ids[0], term_ids[1]

        # Staff
        staff_ids = []
        for i, nm in enumerate(STAFF):
            staff_ids.append(people.create_staff(a, {
                "full_name": nm, "gender": "Female" if nm.split()[0][-1] == "a" else "Male",
                "designation": ("Principal" if i == 0 else "Accountant" if i == 1 else
                                ("Senior teacher" if kind == "school" else "Assistant professor") if i < 6 else
                                ("Teacher" if kind == "school" else "Lecturer")),
                "staff_type": "non-teaching" if i == 1 else "teaching",
                "email": f"{nm.split()[0].lower()}@example.edu", "phone": f"0300-55{i:05d}",
                "joining_date": (today - timedelta(days=200 + 97 * i)).isoformat(),
                "qualifications": "M.Phil" if i % 3 == 0 else "MA / MSc", "employment_status": "active"}))
        teachers = staff_ids[2:]

        # Structure
        classes, subjects = [], []
        if kind == "school":
            for nm, sec in (("Grade 6", "A"), ("Grade 6", "B"), ("Grade 7", "A"), ("Grade 8", "A")):
                classes.append(T.insert("classes", academic_year_id=year, name=nm, section=sec, capacity=35,
                                        class_teacher_id=teachers[len(classes)]))
            for nm, code in (("English", "ENG"), ("Mathematics", "MTH"), ("General Science", "SCI"),
                             ("Social Studies", "SST"), ("Computer Studies", "CMP")):
                subjects.append(T.insert("subjects", name=nm, code=code, credit_hours=1, max_marks=100))
        else:
            fac_ids = []
            if kind == "university":
                fac_ids = [T.insert("faculties", name="Faculty of Computing & Engineering", code="FCE"),
                           T.insert("faculties", name="Faculty of Management Sciences", code="FMS")]
            d_cs = T.insert("departments", name="Computer Science", code="CS", faculty_id=fac_ids[0] if fac_ids else None)
            d_bm = T.insert("departments", name="Management Sciences" if kind == "university" else "Business Administration",
                            code="MS", faculty_id=fac_ids[1] if fac_ids else None)
            for sid, d in zip(staff_ids[2:], [d_cs, d_cs, d_bm, d_cs, d_bm, d_cs, d_bm, d_cs, d_bm]):
                T.update("staff", sid, department_id=d)
            p_cs = T.insert("programs", department_id=d_cs, name="BS Computer Science", code="BSCS",
                            level="Undergraduate", duration_years=4, total_semesters=8)
            p_bm = T.insert("programs", department_id=d_bm, name="MBA" if kind == "university" else "BBA",
                            code="MBA" if kind == "university" else "BBA",
                            level="Graduate" if kind == "university" else "Undergraduate",
                            duration_years=2 if kind == "university" else 4,
                            total_semesters=4 if kind == "university" else 8)
            batch = "Batch " + str(y0 - 1) if kind == "university" else "Semester 3"
            classes.append(T.insert("classes", academic_year_id=year, program_id=p_cs, name=f"BSCS {batch}",
                                    section="A", semester_no=3, capacity=50, class_teacher_id=teachers[0]))
            classes.append(T.insert("classes", academic_year_id=year, program_id=p_cs, name=f"BSCS {batch}",
                                    section="B", semester_no=3, capacity=50, class_teacher_id=teachers[1]))
            classes.append(T.insert("classes", academic_year_id=year, program_id=p_bm,
                                    name=("MBA Batch " + str(y0)) if kind == "university" else "BBA Semester 3",
                                    section="A", semester_no=3, capacity=50, class_teacher_id=teachers[2]))
            for nm, code, cr, prog in (("Data Structures", "CS-201", 4, p_cs), ("Discrete Mathematics", "MT-205", 3, p_cs),
                                       ("Database Systems", "CS-221", 4, p_cs), ("Technical Writing", "HU-210", 2, p_cs),
                                       ("Financial Accounting", "AC-201", 3, p_bm), ("Marketing Management", "MK-210", 3, p_bm),
                                       ("Business Statistics", "ST-220", 3, p_bm), ("Organizational Behaviour", "MG-230", 3, p_bm)):
                subjects.append(T.insert("subjects", name=nm, code=code, credit_hours=cr, program_id=prog,
                                         semester_no=3, max_marks=100))

        # Teacher assignments (one teacher per class subject, rotating)
        k = 0
        for c in classes:
            for sub in academics.subjects_for_class(T, T.get("classes", c)):
                T.insert("teacher_assignments", staff_id=teachers[k % len(teachers)], class_id=c, subject_id=sub["id"])
                k += 1

        # Students and guardians
        used = set()
        student_ids, guardian_ids = [], []
        for ci, c in enumerate(classes):
            cls = T.get("classes", c)
            for j in range(12):
                while True:
                    fn, ln = rnd.choice(FIRST), rnd.choice(LAST)
                    if (fn, ln) not in used:
                        used.add((fn, ln))
                        break
                age = (11 + ci) if kind == "school" else 19 + ci
                g_last = ln
                sid = people.create_student(a, {
                    "first_name": fn, "last_name": ln, "gender": "Female" if fn[-1] in "aehr" else "Male",
                    "dob": date(today.year - age, rnd.randint(1, 12), rnd.randint(1, 28)).isoformat(),
                    "class_id": c, "program_id": cls["program_id"], "academic_year_id": year,
                    "phone": f"0301-{rnd.randint(1000000, 9999999)}", "email": f"{fn.lower()}.{ln.lower()}@student.example.edu",
                    "address": f"House {rnd.randint(1, 300)}, Block {rnd.choice('ABCDEFG')}, Model Town",
                    "emergency_contact": f"0333-{rnd.randint(1000000, 9999999)}",
                    "blood_group": rnd.choice(["A+", "B+", "O+", "AB+", "O-"]),
                    "admission_date": (today - timedelta(days=rnd.randint(60, 700))).isoformat(),
                    "previous_school": rnd.choice(["City Public School", "Green Valley School", "Sunrise Academy"]),
                    "category": "General"}, guardian={
                    "name": f"{rnd.choice(['Imran', 'Shahid', 'Khalid', 'Rashid', 'Nasir', 'Asif'])} {g_last}",
                    "phone": f"0321-{rnd.randint(1000000, 9999999)}", "relationship": "Father",
                    "occupation": rnd.choice(["Engineer", "Doctor", "Business", "Teacher", "Banker"])})
                student_ids.append(sid)
        # Two sibling pairs share a guardian
        for x, y in ((0, 14), (3, 26)):
            g = T.one("student_guardians", "student_id=?", (student_ids[x],))
            people.link_guardian(a, student_ids[y], {"id": g["guardian_id"], "relationship": "Father"})
        guardian_ids = [r["guardian_id"] for r in T.all("student_guardians", "student_id=?", (student_ids[0],))]

        # Attendance for the last 25 working days
        weak = set(rnd.sample(student_ids, 4))
        for d in _weekdays_back(25, a.settings["working_days"]):
            for sid in student_ids:
                p_absent = 0.33 if sid in weak else 0.06
                r = rnd.random()
                status = ("absent" if r < p_absent else "late" if r < p_absent + 0.05 else
                          "leave" if r < p_absent + 0.07 else "present")
                T.insert("attendance", student_id=sid, date=d.isoformat(), status=status,
                         marked_by=owner_uid, marked_at=db.now())
        for d in _weekdays_back(20, a.settings["working_days"]):
            for st in staff_ids:
                T.insert("staff_attendance", staff_id=st, date=d.isoformat(),
                         status="absent" if rnd.random() < 0.04 else "present", marked_by=owner_uid)

        # Fees
        examples = a.profile["fee_examples"]
        ft = {name: T.insert("fee_types", name=name, category="Academic") for name in examples[:5]}
        main_fee = examples[1]
        structures = []
        for c in classes:
            structures.append(T.insert("fee_structures", fee_type_id=ft[main_fee], academic_year_id=year,
                                       class_id=c, frequency="term", amount=25000 if kind == "school" else 85000))
            structures.append(T.insert("fee_structures", fee_type_id=ft["Exam fee"], academic_year_id=year,
                                       class_id=c, frequency="term", amount=2000 if kind == "school" else 5000))
        T.insert("scholarships", student_id=student_ids[1], name="Merit scholarship", eligibility="Top position",
                 discount_type="percent", value=50, effective_from=f"{y0}-08-01", effective_to=f"{y0 + 1}-07-31",
                 approved_by=owner_uid, created_at=db.now())
        issue = max(date(y0, 8, 5), today - timedelta(days=75))
        due = issue + timedelta(days=25)
        term_name = T.get("terms", cur_term)["name"]
        period = f"{term_name} {y0}" if kind == "school" else term_name
        for c in classes:
            sids = [r["id"] for r in T.all("students", "class_id=?", (c,))]
            st_ids = [s for s in structures if T.get("fee_structures", s)["class_id"] == c]
            fees.bulk_generate(a, sids, st_ids, issue.isoformat(), due.isoformat(), period)
        for inv in fees.invoices(T):
            r = rnd.random()
            pay_day = (issue + timedelta(days=rnd.randint(1, max(1, (today - issue).days)))).isoformat()
            if r < 0.6:
                fees.record_payment(a, inv["id"], inv["balance"], rnd.choice(["Cash", "Bank transfer", "Card"]), pay_day)
            elif r < 0.8:
                fees.record_payment(a, inv["id"], round(inv["balance"] / 2, -2), "Cash", pay_day, "Instalment 1")
        unpaid = [i for i in fees.invoices(T) if i["state"] == "unpaid"]
        if unpaid:
            T.insert("discount_requests", invoice_id=unpaid[0]["id"], amount=round(unpaid[0]["balance"] * 0.3, -2),
                     reason="Financial hardship (sibling discount request)", requested_by=owner_uid, created_at=db.now())

        # Exams: previous term final (published) and current midterm
        prev_exam = T.insert("exams", term_id=prev_term, name="Final examination", exam_type="final", weightage=100,
                             start_date=t_names[0][2], end_date=t_names[0][2], status="completed")
        mid = T.insert("exams", term_id=cur_term, name="Midterm examination", exam_type="midterm", weightage=40,
                       start_date=(today - timedelta(days=20)).isoformat(),
                       end_date=(today - timedelta(days=14)).isoformat(), status="completed")
        T.insert("exams", term_id=cur_term, name="Final examination", exam_type="final", weightage=60,
                 start_date=f"{y0}-12-10", end_date=f"{y0}-12-20", status="scheduled")
        ability = {sid: rnd.uniform(0.45, 0.95) for sid in student_ids}
        for ex_i, ex in enumerate((prev_exam, mid)):
            for ci, c in enumerate(classes):
                for si, sub in enumerate(academics.subjects_for_class(T, T.get("classes", c))):
                    ms = exams.get_or_create_marksheet(a, ex, c, sub["id"])
                    entries = []
                    for sid in [r["id"] for r in exams.class_students(T, c)]:
                        absent = rnd.random() < 0.02
                        score = min(100, max(5, round(rnd.gauss(ability[sid] * 100, 9))))
                        entries.append({"student_id": sid, "marks": None if absent else score, "absent": absent})
                    exams.save_marks(a, ms["id"], entries)
                    last = ex_i == 1 and ci == len(classes) - 1
                    steps = ["submit"] if last and si == 0 else ["submit", "review"] if last and si == 1 else \
                        [] if last and si == 2 else ["submit", "review", "approve", "publish"]
                    for step in steps:
                        exams.transition(a, ms["id"], step)

        # Course registration (university)
        if kind == "university":
            for sid in student_ids:
                st = T.get("students", sid)
                for sub in academics.subjects_for_class(T, T.get("classes", st["class_id"])):
                    T.insert("enrollments", student_id=sid, term_id=cur_term, class_id=st["class_id"],
                             subject_id=sub["id"], program_id=st["program_id"], academic_year_id=year,
                             status="enrolled", created_at=db.now())

        # Timetable without clashes
        periods = list(range(1, 6))
        times = {1: ("08:00", "08:45"), 2: ("08:50", "09:35"), 3: ("09:40", "10:25"),
                 4: ("10:45", "11:30"), 5: ("11:35", "12:20")}
        for ci, c in enumerate(classes):
            assigns = T.all("teacher_assignments", "class_id=?", (c,))
            for di, day in enumerate(a.settings["working_days"][:5]):
                for p in periods:
                    asg = assigns[(p + di + ci) % len(assigns)]
                    room = f"R-{101 + ci}"
                    if not attendance.timetable_conflicts(T, day, p, c, asg["staff_id"], room):
                        T.insert("timetable", class_id=c, subject_id=asg["subject_id"], staff_id=asg["staff_id"],
                                 room=room, day=day, period=p, start_time=times[p][0], end_time=times[p][1])

        # Calendar and notices
        for title, typ, d0, d1 in (("Term begins", "term", t_names[1][1], t_names[1][1]),
                                   ("Midterm examinations", "exam", (today - timedelta(days=20)).isoformat(),
                                    (today - timedelta(days=14)).isoformat()),
                                   ("Parent–teacher meeting", "event", (today + timedelta(days=6)).isoformat(),
                                    (today + timedelta(days=6)).isoformat()),
                                   ("Sports gala", "event", (today + timedelta(days=18)).isoformat(),
                                    (today + timedelta(days=19)).isoformat()),
                                   ("Winter break", "holiday", f"{y0}-12-22", f"{y0 + 1}-01-04"),
                                   ("Final examinations", "exam", f"{y0}-12-10", f"{y0}-12-20")):
            T.insert("calendar_events", title=title, event_type=typ, start_date=d0, end_date=d1, created_by=owner_uid)
        for title, body, aud, pr in (
                ("Midterm results published", "Midterm results are now available in the portal. "
                                              "Contact the class teacher for any query.", "all", "normal"),
                ("Fee reminder", "Kindly clear outstanding dues before the end of this month to avoid late fees.",
                 "parents", "high"),
                ("Staff meeting on Friday", "All teaching staff are requested to attend the academic council "
                                            "meeting at 1:30 pm in the conference room.", "staff", "normal")):
            T.insert("notices", title=title, body=body, audience=aud, priority=pr,
                     expiry_date=(today + timedelta(days=30)).isoformat(), created_by=owner_uid, created_at=db.now())

        if kind == "school":
            for c in classes[:2]:
                for sub in academics.subjects_for_class(T, T.get("classes", c))[:2]:
                    hw = T.insert("homework", class_id=c, subject_id=sub["id"], title=f"{sub['name']} worksheet 4",
                                  description="Complete the exercises at the end of the chapter.",
                                  due_date=(today + timedelta(days=3)).isoformat(), created_by=owner_uid,
                                  created_at=db.now())
                    for sid in [r["id"] for r in exams.class_students(T, c)]:
                        T.insert("homework_submissions", homework_id=hw, student_id=sid,
                                 status=rnd.choice(["pending", "submitted", "submitted"]), updated_at=db.now())

        # Admissions pipeline
        for i, status in enumerate(("submitted", "under_review", "waitlisted")):
            people.create_application(a, {
                "first_name": rnd.choice(FIRST), "last_name": rnd.choice(LAST), "gender": "Female",
                "dob": date(today.year - 12, 3, 10 + i).isoformat(), "phone": f"0302-{rnd.randint(1000000, 9999999)}",
                "guardian_name": "Arif " + rnd.choice(LAST), "guardian_phone": "0322-1234567",
                "guardian_relationship": "Father", "applied_class_id": classes[0], "previous_school": "Sunrise Academy",
                "previous_result": "A grade", "status": status,
                "documents": {DOC: (j < 3) for j, DOC in enumerate(people.DOC_CHECKLIST)}})

        # Optional modules
        for title, author, isbn in (("A Brief History of Time", "S. Hawking", "9780553380163"),
                                    ("The Elements of Style", "Strunk & White", "9780205309023"),
                                    ("Introduction to Algorithms", "Cormen et al.", "9780262033848")):
            b = T.insert("books", title=title, author=author, isbn=isbn, category="General")
            for n in range(3):
                T.insert("book_copies", book_id=b, barcode=f"LB-{b:03d}-{n + 1}", status="available")
        copy = T.all("book_copies")[0]
        T.insert("book_issues", copy_id=copy["id"], student_id=student_ids[2],
                 issue_date=(today - timedelta(days=20)).isoformat(), due_date=(today - timedelta(days=6)).isoformat(),
                 issued_by=owner_uid)
        T.update("book_copies", copy["id"], status="issued")
        r1 = T.insert("transport_routes", name="Route 1 – Model Town", stops="Gate 1, Market, Park Road", fee=4000)
        T.insert("transport_vehicles", route_id=r1, reg_no="LEB-1234", capacity=30, driver_name="Akram Khan",
                 driver_phone="0300-7654321")
        for sid in student_ids[:6]:
            T.insert("transport_assignments", student_id=sid, route_id=r1, stop_name="Market",
                     from_date=issue.isoformat())
        room = T.insert("hostel_rooms", building="Iqbal Hall", room_no="101", beds=3, room_type="Triple", fee=15000)
        T.insert("hostel_rooms", building="Iqbal Hall", room_no="102", beds=2, room_type="Double", fee=18000)
        for bed, sid in enumerate(student_ids[-2:], 1):
            T.insert("hostel_allocations", room_id=room, student_id=sid, bed_no=bed, from_date=issue.isoformat())
        for nm, cat, tag in (("Projector – Epson", "IT", "AST-001"), ("Science lab microscope", "Lab", "AST-002"),
                             ("Desktop computer", "IT", "AST-003")):
            T.insert("assets", name=nm, category=cat, tag=tag, location="Main block", condition="good",
                     status="in_use", quantity=1, purchase_date=f"{y0 - 1}-06-01", value=45000)

        # Demo logins
        logins = []
        sfx = a.iid

        def mk(role, label, **kw):
            username = f"{role}{sfx}"
            create_user(a, full_name=kw.pop("name"), username=username, email="", role=role,
                        password=DEMO_PASSWORD, must_change=False, **kw)
            logins.append((label, username, DEMO_PASSWORD))

        mk("principal", "Principal", name=STAFF[0], staff_id=staff_ids[0])
        mk("accountant", "Accountant", name=STAFF[1], staff_id=staff_ids[1])
        mk("teacher", a.profile["staff"], name=STAFF[2], staff_id=staff_ids[2])
        mk("exam_controller", "Exam controller", name=STAFF[5], staff_id=staff_ids[5])
        st0 = T.get("students", student_ids[0])
        mk("parent", "Parent", name=T.get("guardians", guardian_ids[0])["name"], linked_guardian_id=guardian_ids[0])
        mk("student", "Student", name=f"{st0['first_name']} {st0['last_name']}", linked_student_id=st0["id"])

        teacher_uid = T.get("staff", staff_ids[2])["user_id"]
        T.insert("leave_requests", staff_id=staff_ids[3], leave_type="Casual",
                 from_date=(today + timedelta(days=3)).isoformat(), to_date=(today + timedelta(days=4)).isoformat(),
                 days=2, reason="Family function", created_at=db.now())
        a.log("demo_data_loaded", "institution", a.iid, {"students": len(student_ids), "teacher_uid": teacher_uid})
    return logins
