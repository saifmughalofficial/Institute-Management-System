"""Builds the PDF user manual: python docs/build_manual.py"""
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "docs" / "images"
OUT = ROOT / "Institution_Management_System_User_Manual.pdf"
MAKER = "This software is manufactured by Saif Ur Rehman"
INDIGO = colors.HexColor("#4f46e5")
VIOLET = colors.HexColor("#7c3aed")
INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")

ss = getSampleStyleSheet()
BODY = ParagraphStyle("b", parent=ss["BodyText"], fontSize=10.2, leading=14.5, textColor=INK, spaceAfter=5)
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=19, textColor=INDIGO, spaceBefore=4, spaceAfter=10)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13.5, textColor=INK, spaceBefore=10, spaceAfter=6)
CAP = ParagraphStyle("cap", parent=BODY, fontSize=8.5, textColor=MUTED, alignment=TA_CENTER, spaceBefore=3, spaceAfter=10)
TIP = ParagraphStyle("tip", parent=BODY, fontSize=9.6, leading=13.5, textColor=colors.HexColor("#3730a3"))


class Doc(SimpleDocTemplate):
    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name in ("h1", "h2"):
            self.notify("TOCEntry", (0 if f.style.name == "h1" else 1, f.getPlainText(), self.page))


def page_deco(canvas, doc):
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(INDIGO)
    canvas.rect(0, h - 9 * mm, w, 9 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(15 * mm, h - 6 * mm, "Institution Management System · User Manual")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(15 * mm, 9 * mm, MAKER)
    canvas.drawRightString(w - 15 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def cover(canvas, doc):
    w, h = A4
    canvas.saveState()
    for i in range(60):
        t = i / 59
        canvas.setFillColor(colors.Color(0.31 + (0.49 - 0.31) * t, 0.27 + (0.23 - 0.27) * t, 0.9 + (0.93 - 0.9) * t))
        canvas.rect(0, h - (i + 1) * h / 60, w, h / 60 + 1, stroke=0, fill=1)
    canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.08))
    canvas.circle(w - 30 * mm, h - 40 * mm, 60 * mm, stroke=0, fill=1)
    canvas.circle(30 * mm, 50 * mm, 45 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(20 * mm, h - 40 * mm, "SCHOOL  ·  COLLEGE  ·  UNIVERSITY")
    canvas.setFont("Helvetica-Bold", 34)
    canvas.drawString(20 * mm, h - 70 * mm, "Institution")
    canvas.drawString(20 * mm, h - 84 * mm, "Management System")
    canvas.setFont("Helvetica", 16)
    canvas.drawString(20 * mm, h - 100 * mm, "Complete User Manual")
    canvas.setFont("Helvetica", 11)
    for i, line in enumerate(["Multi-tenant · Free · Works offline · No paid API",
                              "Branded for every institution with its own name and logo",
                              f"Version 1.1 · {date.today():%B %Y}"]):
        canvas.drawString(20 * mm, h - 118 * mm - i * 7 * mm, line)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(20 * mm, 30 * mm, MAKER)
    canvas.restoreState()


def p(text):
    return Paragraph(text, BODY)


def steps(items):
    return ListFlowable([ListItem(Paragraph(t, BODY), leftIndent=12) for t in items], bulletType="1",
                        bulletFontName="Helvetica-Bold", bulletColor=INDIGO, leftIndent=16)


def bullets(items):
    return ListFlowable([ListItem(Paragraph(t, BODY), leftIndent=10) for t in items], bulletType="bullet",
                        bulletColor=INDIGO, leftIndent=14, start="•")


def tip(text):
    t = Table([[Paragraph(f"<b>Tip:</b> {text}", TIP)]], colWidths=[178 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef2ff")),
                           ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c7d2fe")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def shot(name, caption, width=172):
    path = IMG / f"{name}.png"
    if not path.exists():
        return Spacer(1, 1)
    from PIL import Image as PImage
    with PImage.open(path) as im:
        w, h = im.size
    height = width * h / w
    if height > 175:
        width, height = width * 175 / height, 175
    img = Image(str(path), width * mm, height * mm)
    frame = Table([[img]], colWidths=[(width + 4) * mm])
    frame.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d1d5db")),
                               ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    return KeepTogether([frame, Paragraph(caption, CAP)])


def table(rows, widths):
    data = [[Paragraph(f"<b>{c}</b>" if i == 0 else c, BODY) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e7ff")),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


story = [PageBreak()]
toc = TableOfContents()
toc.levelStyles = [ParagraphStyle("t1", fontSize=11, leading=17, fontName="Helvetica-Bold", textColor=INK),
                   ParagraphStyle("t2", fontSize=9.5, leading=14, leftIndent=14, textColor=MUTED)]
story += [Paragraph("Contents", ParagraphStyle("contents", parent=H1)), toc, PageBreak()]

# 1
story += [Paragraph("1. Introduction", H1),
          p("The Institution Management System runs a <b>school, college or university</b> from one application. "
            "Each institution gets its own private workspace with its own name and logo. Students, staff, fees, "
            "attendance, exams and files are never visible to any other institution."),
          p("It is written entirely in Python with Streamlit and SQLite. It runs free on your own computer, and "
            "<b>no paid API or internet AI service</b> is used."),
          Paragraph("What you can do", H2),
          bullets(["Register students and guardians, run admissions, upload documents, print ID cards.",
                   "Manage classes, programs, departments, faculties, subjects/courses and teacher assignments.",
                   "Take daily or subject-wise attendance, and track staff attendance and leave.",
                   "Run exams with an approval workflow; print report cards and transcripts (GPA/CGPA).",
                   "Bill fees, collect full or partial payments, issue receipts, apply scholarships and discounts.",
                   "Publish notices, set homework, build timetables and an academic calendar.",
                   "Find anything instantly with the Command center (for example `class Grade 6 A`).",
                   "Export 21 reports to CSV, Excel or PDF; keep a full audit log; back up and restore."])]

# 2
story += [PageBreak(), Paragraph("2. Installing and starting the app", H1),
          Paragraph("On your own Windows computer", H2),
          steps(["Install <b>Python 3.10 or newer</b> from python.org (tick <i>Add Python to PATH</i>).",
                 "Open the project folder <b>Institute Management System</b>.",
                 "Double-click <b>run_local.bat</b>. The first run installs the required free packages automatically.",
                 "Your browser opens <b>http://localhost:8798</b>. If it does not, type that address yourself.",
                 "Keep the black window open while you use the app. Closing it stops the app."]),
          tip("Your data is saved in the <b>data</b> folder inside the project. Back up that folder or use "
              "<b>Backup &amp; restore</b> inside the app."),
          Paragraph("Publishing online (Streamlit Community Cloud, free)", H2),
          steps(["Upload the project folder to a GitHub repository (the <b>data</b> folder is ignored automatically).",
                 "Go to share.streamlit.io, choose <b>New app</b>, select the repository and the file <b>app.py</b>.",
                 "Optional: to stop new institutions signing up publicly, add the secret <b>IMS_ALLOW_SIGNUP = \"0\"</b>."]),
          tip("Storage on Streamlit Cloud is temporary and resets when the app restarts. Download a backup regularly. "
              "After a restart, use <b>Restore from backup</b> on the sign-in page.")]

# 3
story += [PageBreak(), Paragraph("3. First-time setup (6 steps)", H1),
          p("When you open the app for the first time, the setup wizard starts. A progress bar at the top shows "
            "where you are."),
          Paragraph("Step 1 · Choose the institution type", H2),
          p("Click <b>Select School</b>, <b>Select College</b> or <b>Select University</b>. The chosen card shows a "
            "tick, and its button turns purple. Then click <b>Continue</b>."),
          shot("01_choose_type", "Figure 1: Choosing the type of institution"),
          Paragraph("Step 2 · Institution name", H2),
          p("Type your institution's own name, for example <i>Tips College of Science</i>, and choose your currency and "
            "brand colour. Press <b>Enter</b> or click <b>Continue</b>. A blank name is not accepted."),
          shot("02_name", "Figure 2: Entering the institution name"),
          Paragraph("Step 3 · Logo (optional)", H2),
          p("Upload a PNG, JPG or WebP image up to 2 MB, or click <b>Skip for now</b>. Without a logo, the app shows "
            "your initials in a coloured badge everywhere. You can add a logo later in <b>Settings</b>."),
          shot("03_logo", "Figure 3: Optional logo upload with preview"),
          Paragraph("Step 4 · Administrator account", H2),
          p("Enter your name, a username and a password. The password needs at least 8 characters with letters and "
            "numbers. This account is the <b>institution owner</b> and can do everything."),
          shot("04_admin", "Figure 4: Creating the owner account"),
          Paragraph("Step 5 · Review", H2),
          p("Check the summary. Under <b>Start with</b>, keep <b>An empty workspace</b> for your real institution. "
            "Choose <b>Fictional sample data</b> only if you want to test the app with invented records. "
            "Answer the quick maths check and click <b>Create workspace</b>."),
          tip("Added sample data by mistake? On the dashboard click <b>Remove demo data</b> (or Settings → Danger "
              "zone). Your institution name, logo, settings and login are kept."),
          Paragraph("Step 6 · Ready", H2),
          p("Click <b>Open my dashboard</b>. Your institution's name and logo now appear across the app."),
          Paragraph("Just want to look around?", H2),
          p("On the sign-in page, click <b>School demo</b>, <b>College demo</b> or <b>University demo</b>. A separate "
            "practice workspace full of fictional data is created and you are signed in straight away. The "
            "dashboard then lists a login for every role so you can see each person's view."),
          shot("00_signin", "Figure 5: Sign-in page with instant demo buttons")]

# 4
story += [PageBreak(), Paragraph("4. Signing in and finding your way", H1),
          steps(["Enter your <b>username or email</b> and <b>password</b>, then click <b>Sign in</b>.",
                 "The left sidebar lists only the pages your role may use.",
                 "Use the <b>search box</b> at the top of the sidebar, or press <b>Ctrl+K</b>, to find any class, "
                 "student or staff member.",
                 "Click <b>How to use</b> at the top right of a page for quick tips.",
                 "Click <b>Sign out</b> at the bottom of the sidebar when you finish. You are signed out automatically "
                 "after 60 minutes of inactivity."]),
          tip("After 5 wrong passwords an account is locked for 15 minutes. An administrator can reset the password "
              "in <b>Users &amp; roles</b>."),
          Paragraph("The dashboard", H2),
          p("The dashboard shows your institution at a glance. It has a branded banner, quick action tiles, enrolment, "
            "today's attendance, fee collection and outstanding dues. It also shows attendance trends, exam "
            "performance, today's timetable, upcoming events, notices, and <b>Smart insights</b>, which lists "
            "students who may need follow-up."),
          p("A new workspace also shows a <b>Getting started</b> checklist. Click each remaining step to set up your "
            "institution in the right order."),
          shot("06_dashboard", "Figure 6: Dashboard with quick actions and key numbers"),
          shot("07_dashboard_charts", "Figure 7: Charts, schedule, insights, events and notices")]

# 5
story += [PageBreak(), Paragraph("5. Recommended setup order", H1),
          table([["#", "Do this", "Where"],
                 ["1", "Add an academic year and a term/semester; mark them current", "Academics page → Years tab"],
                 ["2", "Colleges/universities: add faculties, departments and programs", "Academics page"],
                 ["3", "Create classes / sections / cohorts", "Academics page → Classes tab"],
                 ["4", "Add subjects or courses (credit hours for higher education)", "Academics page → Subjects tab"],
                 ["5", "Add teachers and staff", "Staff page → Add staff"],
                 ["6", "Assign teachers to classes and subjects", "Academics page → Teacher assignments"],
                 ["7", "Add students one by one, or import a CSV file", "Students page"],
                 ["8", "Create fee types and the fee structure", "Fees & payments → Fee setup"],
                 ["9", "Create logins for staff, parents and students", "Users & roles → Create user"]],
                [10, 100, 68]),
          Spacer(1, 6),
          p("The academics page is called <b>Classes &amp; subjects</b> for schools, <b>Programs &amp; courses</b> for "
            "colleges, and <b>Faculties, programs &amp; courses</b> for universities."),
          shot("15_academics", "Figure 8: Academic structure")]

# 6
story += [PageBreak(), Paragraph("6. Students and admissions", H1),
          Paragraph("Adding a student", H2),
          steps(["Open <b>Students</b> → <b>Add student</b>.",
                 "Fill in the first name (required) and any other details. Leave <i>Admission no</i> blank to generate "
                 "it automatically.",
                 "Add the guardian's name and phone, then click <b>Save student</b>."]),
          Paragraph("Student profile", H2),
          p("Use the <b>Student profile</b> tab to edit details, upload a photo, and link more guardians (siblings "
            "share one guardian record). You can also upload documents, view attendance, fees and results, and "
            "download the <b>ID card</b> or <b>Admission form</b> as a PDF."),
          shot("08_students", "Figure 9: Student directory"),
          Paragraph("Importing many students (CSV)", H2),
          steps(["Open <b>Import CSV</b> and click <b>Download CSV template</b>.",
                 "Fill it in Excel. The class and section must match existing classes; use dates like 2012-04-18.",
                 "Upload the file. The preview shows errors for each row.",
                 "Click <b>Import valid rows</b>, and download the error report to fix the rest."]),
          Paragraph("Promotion, transfer and status", H2),
          p("<b>Promote / transfer</b> moves a whole class to the next class or section. Untick students who repeat "
            "the year. Status changes such as transferred or withdrawn need a reason. When a registrar requests "
            "them, they go to the principal for approval."),
          Paragraph("Admissions", H2),
          p("<b>Admissions</b> records applications with a document checklist. Move each one through Submitted → "
            "Under review → Accepted, Waitlisted or Rejected. <b>Accept &amp; enrol</b> creates the student "
            "automatically, with their guardian and documents.")]

# 7
story += [PageBreak(), Paragraph("7. Attendance", H1),
          steps(["Open <b>Attendance</b> → <b>Mark attendance</b>.",
                 "Choose the date and class (colleges and universities can also choose a subject).",
                 "Everyone starts as <b>present</b>. Change only absent, late, excused or leave students.",
                 "Click <b>Save attendance</b>."]),
          tip("Changing attendance for an earlier day is a <b>correction</b>. It needs a reason and the permission to "
              "correct attendance, and it is recorded in the corrections log."),
          shot("09_attendance", "Figure 10: Marking attendance"),
          p("<b>Register &amp; summary</b> shows percentages for any date range, flags students below the threshold "
            "(75% by default, changeable in Settings), and exports the daily register.")]

# 8
story += [PageBreak(), Paragraph("8. Fees and payments", H1),
          Paragraph("Setting up fees", H2),
          steps(["<b>Fee setup</b>: add fee types (tuition, exam, lab…) and amounts for each class or program.",
                 "<b>Generate invoices</b>: choose a class and the fees to include, type a period label (for example "
                 "Term 1 2026), and click Generate. Students already billed for that period are skipped automatically.",
                 "Active scholarships are deducted automatically on new invoices."]),
          Paragraph("Collecting a payment", H2),
          steps(["Open <b>Collect &amp; manage</b>. By default only students who owe money are listed.",
                 "Choose the student. Their unpaid invoice opens.",
                 "Enter the amount (partial payments are allowed), method and date, then click <b>Record payment</b>.",
                 "Click <b>Receipt</b> to download the PDF receipt with your logo."]),
          shot("10_fees", "Figure 11: Invoice details and payment"),
          Paragraph("Corrections, discounts and refunds", H2),
          bullets(["<b>Reverse</b> a wrong payment (a reason is required). Payments are never deleted, so history stays traceable.",
                   "<b>Discount / waiver</b>: discounts above the set percentage (20% by default) go to the principal for approval.",
                   "<b>Advance credit</b>: extra money can be kept as credit and applied to the next invoice, or refunded.",
                   "<b>Late fees</b>: preview overdue invoices and apply the late-fee rule from Settings."])]

# 9
story += [PageBreak(), Paragraph("9. Exams and results", H1),
          steps(["<b>Exams</b> tab: create an exam in a term and give it a weight (for example midterm 40%, final 60%).",
                 "<b>Marks entry</b>: choose exam, class and subject, type the marks (tick Absent or Exempt if needed), "
                 "then click <b>Save &amp; submit for review</b>.",
                 "Reviewers and the principal open <b>Approvals</b> to review, approve and publish, or to return marks "
                 "with a reason.",
                 "Only <b>published</b> results are visible to students and parents."]),
          shot("11_exams", "Figure 12: Result workflow progress"),
          p("<b>Results</b> shows the class result sheet with positions. Students' report cards (and transcripts with "
            "GPA/CGPA for colleges and universities) download as PDFs. Approved marks are locked; the "
            "<b>Corrections</b> tab changes them with a reason and keeps a record."),
          shot("12_approvals", "Figure 13: Approvals queue")]

# 10
story += [PageBreak(), Paragraph("10. Command center (find anything)", H1),
          p("Open <b>Command center</b>, or type in the sidebar search and press Enter (shortcut <b>Ctrl+K</b>). "
            "Type a command and press Enter:"),
          table([["Command", "What you see"],
                 ["list classes / list departments / list programs / list staff / list subjects", "Every item with counts"],
                 ["class Grade 6 A", "Students, subjects and teachers, timetable, attendance, results, fee balance"],
                 ["department Computer Science", "Programs, classes, staff, courses and student count"],
                 ["program BS Computer Science", "Courses by semester, classes, students"],
                 ["student Ayesha  (or an admission number)", "Profile, guardians, attendance, fees, results"],
                 ["staff Rabia", "Assignments, department, weekly periods"],
                 ["subject Mathematics", "Where it is taught, by whom, average result"],
                 ["help", "List of all commands"]], [80, 98]),
          Spacer(1, 6),
          shot("13_command", "Figure 14: Command center showing one class")]

# 11
story += [PageBreak(), Paragraph("11. Other modules", H1),
          bullets(["<b>Timetable &amp; calendar</b>: weekly timetable per class or teacher. Clashes (the same teacher, "
                   "room or class twice in one period) are blocked automatically. Also holds holidays, exams and events.",
                   "<b>Notices &amp; circulars</b>: post to everyone, staff, students, parents or one class. Shows read "
                   "counts and a printable PDF circular.",
                   "<b>Homework</b>: set work for a class and track who submitted.",
                   "<b>Course registration</b> (universities): register students into courses each semester, with "
                   "credit-hour totals.",
                   "<b>Library, Transport, Hostel, Inventory</b>: switch them on in Settings → Modules."]),
          shot("20_timetable", "Figure 15: Class timetable"),
          shot("19_notices", "Figure 16: Notice board")]

# 12
story += [PageBreak(), Paragraph("12. Reports", H1),
          p("Choose an area (Students, Attendance, Exams, Finance, Staff, Institution) and a report, then set the "
            "filters. Download it as <b>CSV</b>, <b>Excel</b> or <b>PDF</b>. Every file carries your institution's name "
            "and the date, and every export is recorded in the audit log."),
          p("<b>Insights</b> lists students who may need follow-up (low attendance, failed papers in the latest term, "
            "overdue fees) and shows a fee collection trend. All analysis runs offline on your own computer."),
          shot("14_reports", "Figure 17: Report builder")]

# 13
story += [PageBreak(), Paragraph("13. Users, roles and permissions", H1),
          table([["Role", "Typical access"],
                 ["Owner / Administrator", "Everything: settings, users, backups (only the owner can create administrators)"],
                 ["Principal", "Oversight dashboard, approvals (results, discounts, leave, transfers), reports"],
                 ["Vice principal", "Academic monitoring, timetable, attendance corrections"],
                 ["Exam controller", "Exams, marksheets, review and publication"],
                 ["Accountant / Cashier", "Fees, invoices, receipts, financial reports. No access to marks"],
                 ["Teacher / Lecturer", "Only their assigned classes: attendance, marks, homework"],
                 ["Registrar", "Admissions, student records, documents, CSV import"],
                 ["Librarian / Transport / Hostel / Store", "Only their own module"],
                 ["Parent / Student", "Only their own child's or their own attendance, fees, notices and published results"]],
                [55, 123]),
          Spacer(1, 6),
          steps(["Open <b>Users &amp; roles</b> → <b>Create user</b>, choose the role, and link it to a staff, student "
                 "or guardian record.",
                 "A temporary password is shown. The user must change it at first sign-in.",
                 "In <b>Edit user</b>, grant extra permissions or remove ones from the role, reset passwords, or disable "
                 "the account."]),
          shot("16_users", "Figure 18: Users and roles")]

# 14
story += [PageBreak(), Paragraph("14. Settings, backup and security", H1),
          bullets(["<b>Branding &amp; profile</b>: change the name, logo, brand colour, address and date format at any time.",
                   "<b>Academic rules</b>: grading scale, pass mark, GPA standing, attendance threshold, working days.",
                   "<b>Finance rules</b>: currency, invoice/receipt prefixes, late fees, discount approval limit.",
                   "<b>Modules &amp; leave</b>: switch optional modules on or off; set leave allowances.",
                   "<b>Danger zone</b> (owner only): clear all data, for example after testing with demo data."]),
          shot("17_settings", "Figure 19: Settings"),
          Paragraph("Backup and restore", H2),
          p("<b>Backup &amp; restore</b> downloads one ZIP with all of your institution's records and uploaded files. "
            "Keep copies somewhere safe, away from the computer. To restore, upload the ZIP and type the institution "
            "name to confirm."),
          Paragraph("Security built in", H2),
          bullets(["Each institution's data is completely separate; files are private to their institution.",
                   "Passwords are stored only as secure hashes; accounts lock after repeated failed sign-ins.",
                   "Permissions are checked on the server for every action, not just by hiding buttons.",
                   "Important actions (payments, reversals, mark changes, exports, permission changes) are written to "
                   "the <b>Audit log</b>."]),
          Paragraph("Forgotten administrator password", H2),
          p("On the computer running the app, open a terminal in the project folder and run: "
            "<b>python -m ims.cli reset-password &lt;username&gt;</b>")]

# 15
story += [PageBreak(), Paragraph("15. Troubleshooting and FAQ", H1),
          table([["Problem", "Solution"],
                 ["The page does not open", "Make sure run_local.bat is still running, then open http://localhost:8798."],
                 ["I see students I never entered", "Demo data was selected during setup. Click Remove demo data on the dashboard."],
                 ["A page is missing from the sidebar", "Your role does not include it, or the module is switched off in Settings."],
                 ["A teacher cannot see a class", "Assign the teacher in Academics → Teacher assignments."],
                 ["Logo upload refused", "Use PNG, JPG or WebP under 2 MB. The file must be a real image."],
                 ["Cannot edit marks", "Submitted or approved marks are locked. Ask a reviewer to return them, or use Corrections."],
                 ["Cannot cancel an invoice", "Reverse its payments first, then cancel it."],
                 ["Account locked", "Wait 15 minutes, or ask an administrator to reset the password."],
                 ["Data gone after an online restart", "Streamlit Cloud storage is temporary. Restore your latest backup ZIP."]],
                [62, 116]),
          Spacer(1, 18),
          Paragraph(f"<b>{MAKER}</b>", ParagraphStyle("end", parent=BODY, alignment=TA_CENTER, fontSize=12,
                                                       textColor=INDIGO))]

doc = Doc(str(OUT), pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm, leftMargin=15 * mm, rightMargin=15 * mm,
          title="Institution Management System - User Manual", author="Saif Ur Rehman", creator=MAKER)
doc.multiBuild(story, onFirstPage=cover, onLaterPages=page_deco)
print("Wrote", OUT)
