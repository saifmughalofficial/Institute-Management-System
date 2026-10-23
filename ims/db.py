"""SQLite storage, schema and the tenant-scoped repository.

Every institution-owned table carries a NOT NULL ``institution_id``. Pages never
touch those tables directly: they go through :class:`Tenant`, which adds the
institution filter to every read and write and checks that every referenced
row (class_id, student_id, ...) belongs to the same institution.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

_cfg = {
    "db": Path(os.environ.get("IMS_DB_PATH", BASE_DIR / "data" / "ims.sqlite3")),
    "media": Path(os.environ.get("IMS_MEDIA_ROOT", BASE_DIR / "data" / "media")),
}
_local = threading.local()


def configure(db_path=None, media_root=None):
    """Point the app at another database/media folder (used by tests)."""
    if db_path:
        _cfg["db"] = Path(db_path)
    if media_root:
        _cfg["media"] = Path(media_root)


def db_path() -> Path:
    return _cfg["db"]


def media_root() -> Path:
    return _cfg["media"]


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return date.today().isoformat()


# --------------------------------------------------------------------------- #
# Connections
# --------------------------------------------------------------------------- #
def _connect() -> sqlite3.Connection:
    path = _cfg["db"]
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=20000")
    return con


@contextmanager
def transaction():
    """All statements inside run atomically. Nested calls join the outer one."""
    con = getattr(_local, "con", None)
    if con is not None:
        yield con
        return
    con = _connect()
    _local.con = con
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        _local.con = None
        con.close()


def query(sql: str, params=()) -> list[dict]:
    con = getattr(_local, "con", None)
    if con is not None:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    con = _connect()
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def query_one(sql: str, params=()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params=()):
    row = query_one(sql, params)
    return next(iter(row.values())) if row else None


def _exec(sql: str, params=()) -> tuple[int, int]:
    with transaction() as con:
        cur = con.execute(sql, params)
        return cur.lastrowid, cur.rowcount


def execute(sql: str, params=()) -> int:
    """Run a write statement and return lastrowid."""
    return _exec(sql, params)[0]


def execute_count(sql: str, params=()) -> int:
    """Run a write statement and return the number of affected rows."""
    return _exec(sql, params)[1]


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS institutions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL CHECK (length(trim(name)) > 0),
  institution_type TEXT NOT NULL CHECK (institution_type IN ('school','college','university')),
  logo_path TEXT,
  address TEXT, phone TEXT, email TEXT, website TEXT, motto TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  settings_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  username TEXT NOT NULL COLLATE NOCASE UNIQUE,
  email TEXT COLLATE NOCASE,
  full_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  is_owner INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT,
  last_login TEXT,
  linked_student_id INTEGER REFERENCES students(id),
  linked_guardian_id INTEGER REFERENCES guardians(id),
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users(email) WHERE email IS NOT NULL AND email <> '';

CREATE TABLE IF NOT EXISTS user_permissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  perm TEXT NOT NULL,
  granted INTEGER NOT NULL,
  UNIQUE (user_id, perm)
);

CREATE TABLE IF NOT EXISTS academic_years (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  name TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 0,
  UNIQUE (institution_id, name)
);

CREATE TABLE IF NOT EXISTS terms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  academic_year_id INTEGER NOT NULL REFERENCES academic_years(id),
  name TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS faculties (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  name TEXT NOT NULL, code TEXT,
  UNIQUE (institution_id, name)
);

CREATE TABLE IF NOT EXISTS departments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  faculty_id INTEGER REFERENCES faculties(id),
  name TEXT NOT NULL, code TEXT,
  UNIQUE (institution_id, name)
);

CREATE TABLE IF NOT EXISTS programs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  department_id INTEGER REFERENCES departments(id),
  name TEXT NOT NULL, code TEXT, level TEXT,
  duration_years REAL, total_semesters INTEGER,
  UNIQUE (institution_id, name)
);

CREATE TABLE IF NOT EXISTS staff (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  user_id INTEGER REFERENCES users(id),
  staff_no TEXT NOT NULL,
  full_name TEXT NOT NULL,
  gender TEXT, email TEXT, phone TEXT,
  designation TEXT, staff_type TEXT DEFAULT 'teaching',
  department_id INTEGER REFERENCES departments(id),
  joining_date TEXT, qualifications TEXT,
  employment_status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  UNIQUE (institution_id, staff_no)
);

CREATE TABLE IF NOT EXISTS classes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  academic_year_id INTEGER REFERENCES academic_years(id),
  program_id INTEGER REFERENCES programs(id),
  name TEXT NOT NULL, section TEXT DEFAULT '',
  semester_no INTEGER, capacity INTEGER,
  class_teacher_id INTEGER REFERENCES staff(id),
  is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS subjects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  name TEXT NOT NULL, code TEXT,
  credit_hours REAL NOT NULL DEFAULT 1 CHECK (credit_hours >= 0),
  program_id INTEGER REFERENCES programs(id),
  class_id INTEGER REFERENCES classes(id),
  semester_no INTEGER,
  is_elective INTEGER NOT NULL DEFAULT 0,
  max_marks REAL NOT NULL DEFAULT 100 CHECK (max_marks > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_subject_code ON subjects(institution_id, code) WHERE code IS NOT NULL AND code <> '';

CREATE TABLE IF NOT EXISTS teacher_assignments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  staff_id INTEGER NOT NULL REFERENCES staff(id),
  class_id INTEGER NOT NULL REFERENCES classes(id),
  subject_id INTEGER REFERENCES subjects(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_teacher_assign ON teacher_assignments(staff_id, class_id, IFNULL(subject_id, 0));

CREATE TABLE IF NOT EXISTS students (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  admission_no TEXT NOT NULL,
  first_name TEXT NOT NULL, last_name TEXT DEFAULT '',
  gender TEXT, dob TEXT, email TEXT, phone TEXT, address TEXT,
  emergency_contact TEXT, blood_group TEXT, national_id TEXT,
  photo_path TEXT,
  class_id INTEGER REFERENCES classes(id),
  program_id INTEGER REFERENCES programs(id),
  academic_year_id INTEGER REFERENCES academic_years(id),
  admission_date TEXT, previous_school TEXT,
  category TEXT DEFAULT 'General',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL, updated_at TEXT,
  UNIQUE (institution_id, admission_no)
);
CREATE INDEX IF NOT EXISTS ix_students_class ON students(institution_id, class_id);

CREATE TABLE IF NOT EXISTS guardians (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  name TEXT NOT NULL, phone TEXT, email TEXT, address TEXT,
  occupation TEXT, national_id TEXT
);

CREATE TABLE IF NOT EXISTS student_guardians (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  guardian_id INTEGER NOT NULL REFERENCES guardians(id),
  relationship TEXT, is_primary INTEGER NOT NULL DEFAULT 0,
  UNIQUE (student_id, guardian_id)
);

CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  application_no TEXT NOT NULL,
  first_name TEXT NOT NULL, last_name TEXT DEFAULT '',
  gender TEXT, dob TEXT, email TEXT, phone TEXT, address TEXT,
  guardian_name TEXT, guardian_phone TEXT, guardian_relationship TEXT,
  applied_class_id INTEGER REFERENCES classes(id),
  applied_program_id INTEGER REFERENCES programs(id),
  previous_school TEXT, previous_result TEXT,
  documents_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'draft',
  notes TEXT,
  student_id INTEGER REFERENCES students(id),
  created_by INTEGER REFERENCES users(id),
  decided_by INTEGER REFERENCES users(id),
  decided_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (institution_id, application_no)
);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  student_id INTEGER REFERENCES students(id),
  staff_id INTEGER REFERENCES staff(id),
  application_id INTEGER REFERENCES applications(id),
  doc_type TEXT NOT NULL, file_path TEXT NOT NULL,
  original_name TEXT, mime TEXT, size INTEGER,
  uploaded_by INTEGER REFERENCES users(id),
  uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS student_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  event TEXT NOT NULL, from_value TEXT, to_value TEXT, reason TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  request_type TEXT NOT NULL,
  student_id INTEGER REFERENCES students(id),
  payload_json TEXT NOT NULL DEFAULT '{}',
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  requested_by INTEGER REFERENCES users(id),
  decided_by INTEGER REFERENCES users(id),
  decided_at TEXT, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enrollments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  academic_year_id INTEGER REFERENCES academic_years(id),
  term_id INTEGER REFERENCES terms(id),
  class_id INTEGER REFERENCES classes(id),
  program_id INTEGER REFERENCES programs(id),
  subject_id INTEGER REFERENCES subjects(id),
  status TEXT NOT NULL DEFAULT 'enrolled',
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_enrol_course ON enrollments(student_id, IFNULL(term_id,0), IFNULL(subject_id,0), IFNULL(class_id,0));

CREATE TABLE IF NOT EXISTS attendance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  date TEXT NOT NULL,
  subject_id INTEGER REFERENCES subjects(id),
  status TEXT NOT NULL CHECK (status IN ('present','absent','late','excused','leave')),
  remark TEXT,
  marked_by INTEGER REFERENCES users(id),
  marked_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_attendance ON attendance(institution_id, student_id, date, IFNULL(subject_id,0));
CREATE INDEX IF NOT EXISTS ix_attendance_date ON attendance(institution_id, date);

CREATE TABLE IF NOT EXISTS attendance_corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  attendance_id INTEGER NOT NULL REFERENCES attendance(id),
  old_status TEXT, new_status TEXT, reason TEXT NOT NULL,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS staff_attendance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  staff_id INTEGER NOT NULL REFERENCES staff(id),
  date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('present','absent','late','excused','leave')),
  remark TEXT,
  marked_by INTEGER REFERENCES users(id),
  UNIQUE (institution_id, staff_id, date)
);

CREATE TABLE IF NOT EXISTS leave_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  staff_id INTEGER NOT NULL REFERENCES staff(id),
  leave_type TEXT NOT NULL,
  from_date TEXT NOT NULL, to_date TEXT NOT NULL,
  days REAL NOT NULL CHECK (days > 0),
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  decided_by INTEGER REFERENCES users(id),
  decided_at TEXT, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS timetable (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  class_id INTEGER NOT NULL REFERENCES classes(id),
  subject_id INTEGER REFERENCES subjects(id),
  staff_id INTEGER REFERENCES staff(id),
  room TEXT DEFAULT '',
  day TEXT NOT NULL, period INTEGER NOT NULL,
  start_time TEXT, end_time TEXT
);

CREATE TABLE IF NOT EXISTS calendar_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  title TEXT NOT NULL, event_type TEXT NOT NULL,
  start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  description TEXT,
  created_by INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS fee_types (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  name TEXT NOT NULL, category TEXT,
  UNIQUE (institution_id, name)
);

CREATE TABLE IF NOT EXISTS fee_structures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  fee_type_id INTEGER NOT NULL REFERENCES fee_types(id),
  academic_year_id INTEGER REFERENCES academic_years(id),
  class_id INTEGER REFERENCES classes(id),
  program_id INTEGER REFERENCES programs(id),
  semester_no INTEGER,
  student_category TEXT,
  frequency TEXT NOT NULL DEFAULT 'term',
  amount REAL NOT NULL CHECK (amount > 0)
);

CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  invoice_no TEXT NOT NULL,
  student_id INTEGER NOT NULL REFERENCES students(id),
  period_label TEXT,
  issue_date TEXT NOT NULL, due_date TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'issued' CHECK (status IN ('issued','cancelled')),
  notes TEXT,
  late_fee_applied_on TEXT,
  created_by INTEGER REFERENCES users(id),
  cancelled_by INTEGER REFERENCES users(id),
  cancelled_reason TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (institution_id, invoice_no),
  CHECK (due_date >= issue_date)
);

CREATE TABLE IF NOT EXISTS invoice_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  fee_type_id INTEGER REFERENCES fee_types(id),
  item_type TEXT NOT NULL DEFAULT 'fee' CHECK (item_type IN ('fee','discount','scholarship','late_fee')),
  description TEXT NOT NULL,
  amount REAL NOT NULL,
  CHECK ((item_type IN ('fee','late_fee') AND amount > 0) OR (item_type IN ('discount','scholarship') AND amount < 0))
);

CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  receipt_no TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'payment' CHECK (kind IN ('payment','credit_applied','reversal')),
  amount REAL NOT NULL,
  method TEXT NOT NULL,
  reference TEXT,
  payment_date TEXT NOT NULL,
  reverses_payment_id INTEGER REFERENCES payments(id),
  is_reversed INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  recorded_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  UNIQUE (institution_id, receipt_no),
  CHECK ((kind = 'reversal' AND amount < 0) OR (kind <> 'reversal' AND amount > 0))
);

CREATE TABLE IF NOT EXISTS student_credits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  amount REAL NOT NULL CHECK (amount <> 0),
  kind TEXT NOT NULL CHECK (kind IN ('overpayment','applied','refund','restored','adjustment')),
  payment_id INTEGER REFERENCES payments(id),
  method TEXT, reason TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discount_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  amount REAL NOT NULL CHECK (amount > 0),
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  requested_by INTEGER REFERENCES users(id),
  decided_by INTEGER REFERENCES users(id),
  decided_at TEXT, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scholarships (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  name TEXT NOT NULL, eligibility TEXT,
  discount_type TEXT NOT NULL CHECK (discount_type IN ('percent','fixed')),
  value REAL NOT NULL CHECK (value > 0),
  effective_from TEXT NOT NULL, effective_to TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  approved_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exams (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  term_id INTEGER NOT NULL REFERENCES terms(id),
  name TEXT NOT NULL,
  exam_type TEXT NOT NULL DEFAULT 'final',
  weightage REAL NOT NULL DEFAULT 100 CHECK (weightage > 0 AND weightage <= 100),
  start_date TEXT, end_date TEXT,
  status TEXT NOT NULL DEFAULT 'scheduled'
);

CREATE TABLE IF NOT EXISTS marksheets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  exam_id INTEGER NOT NULL REFERENCES exams(id),
  class_id INTEGER NOT NULL REFERENCES classes(id),
  subject_id INTEGER NOT NULL REFERENCES subjects(id),
  max_marks REAL NOT NULL CHECK (max_marks > 0),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','submitted','reviewed','approved','published')),
  submitted_by INTEGER REFERENCES users(id), submitted_at TEXT,
  reviewed_by INTEGER REFERENCES users(id), reviewed_at TEXT,
  approved_by INTEGER REFERENCES users(id), approved_at TEXT,
  published_by INTEGER REFERENCES users(id), published_at TEXT,
  return_reason TEXT,
  UNIQUE (institution_id, exam_id, class_id, subject_id)
);

CREATE TABLE IF NOT EXISTS results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  marksheet_id INTEGER NOT NULL REFERENCES marksheets(id),
  exam_id INTEGER NOT NULL REFERENCES exams(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  subject_id INTEGER NOT NULL REFERENCES subjects(id),
  max_marks REAL NOT NULL CHECK (max_marks > 0),
  obtained_marks REAL CHECK (obtained_marks IS NULL OR (obtained_marks >= 0 AND obtained_marks <= max_marks)),
  is_absent INTEGER NOT NULL DEFAULT 0,
  is_exempt INTEGER NOT NULL DEFAULT 0,
  grade TEXT, grade_point REAL, remarks TEXT,
  UNIQUE (marksheet_id, student_id)
);

CREATE TABLE IF NOT EXISTS result_corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  result_id INTEGER NOT NULL REFERENCES results(id),
  old_value TEXT, new_value TEXT, reason TEXT NOT NULL,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  title TEXT NOT NULL, body TEXT NOT NULL,
  audience TEXT NOT NULL DEFAULT 'all',
  class_id INTEGER REFERENCES classes(id),
  program_id INTEGER REFERENCES programs(id),
  priority TEXT NOT NULL DEFAULT 'normal',
  expiry_date TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notice_reads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  notice_id INTEGER NOT NULL REFERENCES notices(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  read_at TEXT NOT NULL,
  UNIQUE (notice_id, user_id)
);

CREATE TABLE IF NOT EXISTS homework (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  class_id INTEGER NOT NULL REFERENCES classes(id),
  subject_id INTEGER REFERENCES subjects(id),
  title TEXT NOT NULL, description TEXT,
  due_date TEXT NOT NULL,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS homework_submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  homework_id INTEGER NOT NULL REFERENCES homework(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  status TEXT NOT NULL DEFAULT 'pending',
  remarks TEXT, updated_at TEXT,
  UNIQUE (homework_id, student_id)
);

CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  title TEXT NOT NULL, author TEXT, isbn TEXT, category TEXT, publisher TEXT
);

CREATE TABLE IF NOT EXISTS book_copies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  book_id INTEGER NOT NULL REFERENCES books(id),
  barcode TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'available',
  UNIQUE (institution_id, barcode)
);

CREATE TABLE IF NOT EXISTS book_issues (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  copy_id INTEGER NOT NULL REFERENCES book_copies(id),
  student_id INTEGER REFERENCES students(id),
  staff_id INTEGER REFERENCES staff(id),
  issue_date TEXT NOT NULL, due_date TEXT NOT NULL, return_date TEXT,
  renewals INTEGER NOT NULL DEFAULT 0,
  fine REAL NOT NULL DEFAULT 0,
  issued_by INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS transport_routes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  name TEXT NOT NULL, stops TEXT, fee REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transport_vehicles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  route_id INTEGER REFERENCES transport_routes(id),
  reg_no TEXT NOT NULL, capacity INTEGER, driver_name TEXT, driver_phone TEXT
);

CREATE TABLE IF NOT EXISTS transport_assignments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  route_id INTEGER NOT NULL REFERENCES transport_routes(id),
  stop_name TEXT, from_date TEXT,
  status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS hostel_rooms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  building TEXT NOT NULL, room_no TEXT NOT NULL,
  beds INTEGER NOT NULL CHECK (beds > 0),
  room_type TEXT, fee REAL NOT NULL DEFAULT 0,
  UNIQUE (institution_id, building, room_no)
);

CREATE TABLE IF NOT EXISTS hostel_allocations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  room_id INTEGER NOT NULL REFERENCES hostel_rooms(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  bed_no INTEGER, from_date TEXT, to_date TEXT,
  status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS maintenance_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  room_id INTEGER REFERENCES hostel_rooms(id),
  asset_id INTEGER REFERENCES assets(id),
  description TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  name TEXT NOT NULL, category TEXT, tag TEXT,
  location TEXT, condition TEXT DEFAULT 'good',
  status TEXT NOT NULL DEFAULT 'in_stock',
  assigned_to TEXT, quantity INTEGER NOT NULL DEFAULT 1,
  purchase_date TEXT, value REAL, notes TEXT
);

CREATE TABLE IF NOT EXISTS asset_movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  asset_id INTEGER NOT NULL REFERENCES assets(id),
  action TEXT NOT NULL, details TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  user_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL,
  object_type TEXT, object_id INTEGER,
  details TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit ON audit_log(institution_id, created_at);

CREATE TABLE IF NOT EXISTS counters (
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  key TEXT NOT NULL,
  value INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (institution_id, key)
);

CREATE TABLE IF NOT EXISTS signup_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_key TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

# Every table that belongs to one institution (all except the platform tables).
TENANT_TABLES = {
    "users", "user_permissions", "academic_years", "terms", "faculties", "departments",
    "programs", "staff", "classes", "subjects", "teacher_assignments", "students",
    "guardians", "student_guardians", "applications", "documents", "student_history",
    "change_requests", "enrollments", "attendance", "attendance_corrections",
    "staff_attendance", "leave_requests", "timetable", "calendar_events", "fee_types",
    "fee_structures", "invoices", "invoice_items", "payments", "student_credits",
    "discount_requests", "scholarships", "exams", "marksheets", "results",
    "result_corrections", "notices", "notice_reads", "homework", "homework_submissions",
    "books", "book_copies", "book_issues", "transport_routes", "transport_vehicles",
    "transport_assignments", "hostel_rooms", "hostel_allocations", "maintenance_requests",
    "assets", "asset_movements", "audit_log", "counters",
}

# Column name -> table it references. Used to verify cross-tenant references on
# every insert/update and to validate backups before restoring them.
FK_MAP = {
    "user_id": "users", "academic_year_id": "academic_years", "term_id": "terms",
    "faculty_id": "faculties", "department_id": "departments", "program_id": "programs",
    "staff_id": "staff", "class_id": "classes", "subject_id": "subjects",
    "student_id": "students", "guardian_id": "guardians", "application_id": "applications",
    "attendance_id": "attendance", "fee_type_id": "fee_types", "invoice_id": "invoices",
    "payment_id": "payments", "reverses_payment_id": "payments", "exam_id": "exams",
    "marksheet_id": "marksheets", "result_id": "results", "notice_id": "notices",
    "homework_id": "homework", "book_id": "books", "copy_id": "book_copies",
    "route_id": "transport_routes", "room_id": "hostel_rooms", "asset_id": "assets",
    "class_teacher_id": "staff", "applied_class_id": "classes",
    "applied_program_id": "programs", "linked_student_id": "students",
    "linked_guardian_id": "guardians", "marked_by": "users", "recorded_by": "users",
    "created_by": "users", "decided_by": "users", "requested_by": "users",
    "approved_by": "users", "uploaded_by": "users", "issued_by": "users",
    "cancelled_by": "users", "submitted_by": "users", "reviewed_by": "users",
    "published_by": "users",
}


def init_db():
    con = _connect()
    try:
        con.executescript(SCHEMA)
        con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),))
        con.commit()
    finally:
        con.close()
    media_root().mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Tenant-scoped repository
# --------------------------------------------------------------------------- #
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


class TenantError(PermissionError):
    """Raised when a record does not belong to the current institution."""


class Tenant:
    def __init__(self, institution_id: int):
        self.iid = int(institution_id)

    @staticmethod
    def _t(table: str) -> str:
        if table not in TENANT_TABLES:
            raise TenantError(f"'{table}' is not an institution-owned table")
        return table

    @staticmethod
    def _clean(data: dict) -> dict:
        data = {k: v for k, v in data.items() if k not in ("id", "institution_id")}
        for k in data:
            if not _IDENT.match(k):
                raise ValueError(f"Invalid column name: {k}")
        return data

    def _check_refs(self, data: dict):
        for col, val in data.items():
            ref = FK_MAP.get(col)
            if ref and val not in (None, ""):
                if not self.get(ref, val):
                    raise TenantError(f"{col}={val} does not belong to this institution")

    # reads ------------------------------------------------------------------
    def all(self, table, where="", params=(), order="id") -> list[dict]:
        sql = f"SELECT * FROM {self._t(table)} WHERE institution_id=?"
        if where:
            sql += f" AND ({where})"
        if order:
            sql += f" ORDER BY {order}"
        return query(sql, (self.iid, *params))

    def one(self, table, where, params=()) -> dict | None:
        rows = self.all(table, where, params, order="id LIMIT 1")
        return rows[0] if rows else None

    def get(self, table, row_id) -> dict | None:
        if row_id in (None, ""):
            return None
        try:
            row_id = int(row_id)
        except (TypeError, ValueError):
            return None
        return query_one(f"SELECT * FROM {self._t(table)} WHERE id=? AND institution_id=?",
                         (row_id, self.iid))

    def require(self, table, row_id) -> dict:
        row = self.get(table, row_id)
        if not row:
            raise TenantError("Record not found in this institution.")
        return row

    def count(self, table, where="", params=()) -> int:
        sql = f"SELECT COUNT(*) FROM {self._t(table)} WHERE institution_id=?"
        if where:
            sql += f" AND ({where})"
        return int(scalar(sql, (self.iid, *params)) or 0)

    def q(self, sql: str, params: dict | None = None) -> list[dict]:
        """Raw scoped SQL. It must filter by ``institution_id=:iid``."""
        if "institution_id=:iid" not in sql.replace(" ", ""):
            raise TenantError("Scoped SQL must filter by institution_id=:iid")
        p = dict(params or {})
        p["iid"] = self.iid
        return query(sql, p)

    def q1(self, sql: str, params: dict | None = None) -> dict | None:
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: dict | None = None):
        row = self.q1(sql, params)
        return next(iter(row.values())) if row else None

    # writes -----------------------------------------------------------------
    def insert(self, table, **data) -> int:
        data = self._clean(data)
        self._check_refs(data)
        cols = ["institution_id", *data]
        sql = (f"INSERT INTO {self._t(table)} ({', '.join(cols)}) "
               f"VALUES ({', '.join('?' * len(cols))})")
        return execute(sql, (self.iid, *data.values()))

    def update(self, table, row_id, **data) -> None:
        data = self._clean(data)
        if not data:
            return
        self._check_refs(data)
        sets = ", ".join(f"{k}=?" for k in data)
        n = execute_count(f"UPDATE {self._t(table)} SET {sets} WHERE id=? AND institution_id=?",
                          (*data.values(), int(row_id), self.iid))
        if n == 0:
            raise TenantError("Record not found in this institution.")

    def delete(self, table, row_id) -> None:
        n = execute_count(f"DELETE FROM {self._t(table)} WHERE id=? AND institution_id=?",
                          (int(row_id), self.iid))
        if n == 0:
            raise TenantError("Record not found in this institution.")

    def next_number(self, key: str, prefix: str, width: int = 5) -> str:
        """Next value of a per-institution sequence, e.g. INV-2026-00012."""
        with transaction():
            execute("INSERT OR IGNORE INTO counters(institution_id, key, value) VALUES (?,?,0)",
                    (self.iid, key))
            execute("UPDATE counters SET value=value+1 WHERE institution_id=? AND key=?",
                    (self.iid, key))
            value = scalar("SELECT value FROM counters WHERE institution_id=? AND key=?",
                           (self.iid, key))
        return f"{prefix}-{date.today().year}-{int(value):0{width}d}"
