# Institution Management System

One configurable, multi-tenant platform for **schools, colleges and universities**. Built with Python, Streamlit and SQLite. It runs free on your own computer and needs no paid API.

## Run locally (Windows)
Double-click `run_local.bat`, or run:
```
pip install -r requirements.txt
streamlit run app.py --server.port 8798
```
Open http://localhost:8798. The first visit opens the setup wizard:
1. Choose the type (School, College or University).
2. Enter the name.
3. Upload a logo, or skip it.
4. Create the administrator account.
5. Review the details and create the workspace.
6. Open the dashboard.

To explore every feature with fictional data, tick **Load demo data** on the review step.

## Deploy on Streamlit Community Cloud (free)
1. Push this folder to a GitHub repository. `data/` is ignored, so no data is uploaded.
2. On share.streamlit.io, choose **New app** and select `app.py`.
3. Optional: to stop new institutions signing up publicly, add the secret `IMS_ALLOW_SIGNUP = "0"`.

Streamlit Cloud storage is **temporary**: the database resets whenever the app restarts. Download backups from **Backup & restore** regularly. After a restart, use **Restore from backup** on the sign-in page. For permanent production use, move to PostgreSQL, private file storage, HTTPS and monitored backups.

## What's inside
| Area | Features |
|---|---|
| Onboarding | Three type cards, name validation, logo checks (type, real content, 2 MB limit, re-encoded) with a monogram fallback, owner account, rate-limited signup with a simple human check |
| Tenant isolation | Every record has a non-null `institution_id`. All access goes through the `Tenant` repository, which filters every query and checks every referenced id. Files are private per institution. Backups are validated row by row before restore |
| Roles | Owner, admin, principal, vice principal, exam controller, accountant, cashier, teacher, registrar, librarian, transport, hostel, store, parent and student. Each user can get individual grants or revocations. Permissions are checked on the server |
| Students | Admissions pipeline, profiles, guardians and siblings, documents, ID cards, admission forms, status changes and transfers with approval, promotion, CSV import with preview |
| Academics | Years, terms/semesters, faculties, departments, programs, classes/cohorts, subjects/courses with credit hours, teacher assignments, course registration (university) |
| Attendance | Daily and subject-wise attendance, bulk marking, corrections with reasons, percentages, low-attendance alerts, registers, staff attendance and leave |
| Timetable | Class and teacher timetables with clash detection, academic calendar |
| Exams | Weighted exams, supplementary exams, grading scales, GPA/CGPA. Workflow: Draft → Submitted → Reviewed → Approved → Published. Results lock after approval; corrections need a reason and are logged. Report cards and transcripts as PDF |
| Finance | Fee types and structures, single or bulk invoices, scholarships, discounts that need approval above a threshold, partial payments, advance credit, receipts, reversals (payments are never deleted), refunds, late fees, ledgers |
| Communication | Targeted notices with read tracking and printable circulars, homework |
| Reports | 21 reports exportable to CSV, Excel and PDF with the institution's name and logo. Every export is logged. Offline rule-based insights flag at-risk students and project fee collection |
| Modules | Library, transport, hostel and inventory, each switchable on or off |
| Admin | Settings, audit log, backup and restore, ownership transfer |

## Tests
```
python -m pytest tests -q
```
The suite checks tenant isolation, upload validation, lockout, role limits, finance reconciliation, the result workflow and backup round-trips. It also renders every page for 7 roles across all 3 institution types.

## Admin account recovery
On the server: `python -m ims.cli reset-password <username>`

---
This software is manufactured by **Saif Ur Rehman**.
