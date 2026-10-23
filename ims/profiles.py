"""Institution-type configuration: labels, enabled features and default settings.

One shared schema serves all three types; the profile decides what the
interface calls things and which features are shown.
"""
from __future__ import annotations

import copy
import json

PROFILES = {
    "school": {
        "title": "School Management System",
        "short": "School",
        "icon": ":material/backpack:",
        "tagline": "Grades, sections, guardians, attendance, school fees, exams and report cards.",
        "class": "Class", "classes": "Classes", "section": "Section",
        "program": None, "programs": None,
        "term": "Term", "terms": "Terms",
        "subject": "Subject", "subjects": "Subjects",
        "staff": "Teacher", "staff_plural": "Teachers & staff",
        "academics_page": "Classes & subjects",
        "departments": False, "faculties": False, "programs_enabled": False,
        "credit_hours": False, "gpa": False, "transcript": False,
        "course_registration": False, "subject_attendance": False,
        "guardians_emphasis": True,
        "result_doc": "Report card",
        "fee_examples": ["Admission fee", "Tuition fee", "Monthly fee", "Exam fee",
                         "Lab fee", "Library fee", "Transport fee", "Activity fee"],
    },
    "college": {
        "title": "College Management System",
        "short": "College",
        "icon": ":material/menu_book:",
        "tagline": "Programs, departments, semesters/terms, subjects, faculty, attendance, fees and results.",
        "class": "Class / cohort", "classes": "Classes / cohorts", "section": "Section",
        "program": "Program", "programs": "Programs",
        "term": "Semester", "terms": "Semesters",
        "subject": "Course", "subjects": "Courses",
        "staff": "Faculty member", "staff_plural": "Faculty & staff",
        "academics_page": "Programs & courses",
        "departments": True, "faculties": False, "programs_enabled": True,
        "credit_hours": True, "gpa": True, "transcript": False,
        "course_registration": False, "subject_attendance": True,
        "guardians_emphasis": False,
        "result_doc": "Semester result",
        "fee_examples": ["Admission fee", "Semester fee", "Tuition fee", "Exam fee",
                         "Lab fee", "Library fee", "Hostel fee", "Transport fee"],
    },
    "university": {
        "title": "University Management System",
        "short": "University",
        "icon": ":material/account_balance:",
        "tagline": "Faculties, departments, programs, semesters, courses, faculty, enrollment, "
                   "credit hours, exams and transcripts.",
        "class": "Cohort / batch", "classes": "Cohorts / batches", "section": "Section",
        "program": "Degree program", "programs": "Degree programs",
        "term": "Semester", "terms": "Semesters",
        "subject": "Course", "subjects": "Courses",
        "staff": "Faculty member", "staff_plural": "Faculty, researchers & staff",
        "academics_page": "Faculties, programs & courses",
        "departments": True, "faculties": True, "programs_enabled": True,
        "credit_hours": True, "gpa": True, "transcript": True,
        "course_registration": True, "subject_attendance": True,
        "guardians_emphasis": False,
        "result_doc": "Transcript",
        "fee_examples": ["Admission fee", "Tuition fee", "Program fee", "Semester fee",
                         "Exam fee", "Library fee", "Hostel fee", "Transport fee"],
    },
}

INSTITUTION_TYPES = list(PROFILES)

SCHOOL_SCALE = [
    {"min": 90, "grade": "A+", "point": 4.0}, {"min": 80, "grade": "A", "point": 4.0},
    {"min": 70, "grade": "B", "point": 3.0}, {"min": 60, "grade": "C", "point": 2.0},
    {"min": 50, "grade": "D", "point": 1.0}, {"min": 40, "grade": "E", "point": 0.5},
    {"min": 0, "grade": "F", "point": 0.0},
]
HIGHER_ED_SCALE = [
    {"min": 85, "grade": "A", "point": 4.0}, {"min": 80, "grade": "A-", "point": 3.7},
    {"min": 75, "grade": "B+", "point": 3.3}, {"min": 71, "grade": "B", "point": 3.0},
    {"min": 68, "grade": "B-", "point": 2.7}, {"min": 64, "grade": "C+", "point": 2.3},
    {"min": 61, "grade": "C", "point": 2.0}, {"min": 58, "grade": "C-", "point": 1.7},
    {"min": 54, "grade": "D+", "point": 1.3}, {"min": 50, "grade": "D", "point": 1.0},
    {"min": 0, "grade": "F", "point": 0.0},
]

ACCENTS = {
    "Indigo": ("#4f46e5", "#7c3aed"),
    "Emerald": ("#059669", "#0d9488"),
    "Ocean": ("#0284c7", "#2563eb"),
    "Crimson": ("#dc2626", "#db2777"),
    "Amber": ("#d97706", "#ea580c"),
    "Slate": ("#334155", "#475569"),
}

CURRENCIES = ["PKR", "USD", "EUR", "GBP", "INR", "AED", "SAR", "BDT", "NGN", "KES", "CAD", "AUD"]
DATE_FORMATS = {"23-Oct-2026": "%d-%b-%Y", "23/10/2026": "%d/%m/%Y",
                "10/23/2026": "%m/%d/%Y", "2026-10-23": "%Y-%m-%d"}

OPTIONAL_MODULES = {
    "admissions": "Admissions workflow",
    "timetable": "Timetable & calendar",
    "homework": "Homework / assignments",
    "library": "Library",
    "transport": "Transport",
    "hostel": "Hostel",
    "assets": "Inventory & assets",
}


def default_settings(institution_type: str) -> dict:
    higher = institution_type != "school"
    return {
        "currency": "PKR",
        "date_format": "%d-%b-%Y",
        "accent": "Indigo",
        "grading_scale": copy.deepcopy(HIGHER_ED_SCALE if higher else SCHOOL_SCALE),
        "pass_percent": 50 if higher else 40,
        "standing_min_gpa": 2.0,
        "attendance_threshold": 75,
        "invoice_prefix": "INV", "receipt_prefix": "RCP", "reversal_prefix": "REV",
        "application_prefix": "APP", "admission_prefix": "ADM", "staff_prefix": "EMP",
        "late_fee_type": "flat", "late_fee_amount": 0.0, "late_fee_grace_days": 0,
        "discount_approval_percent": 20,
        "library_loan_days": 14, "library_fine_per_day": 10.0,
        "periods_per_day": 7,
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"] + ([] if higher else ["Sat"]),
        "leave_allowance": {"Casual": 10, "Sick": 8, "Annual": 14},
        "modules": {"admissions": True, "timetable": True, "homework": not higher,
                    "library": False, "transport": False, "hostel": False, "assets": False},
    }


def load_settings(inst: dict) -> dict:
    """Stored settings merged over the defaults so new keys always exist."""
    base = default_settings(inst["institution_type"])
    try:
        stored = json.loads(inst.get("settings_json") or "{}")
    except json.JSONDecodeError:
        stored = {}
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key].update(value)
        else:
            base[key] = value
    return base
