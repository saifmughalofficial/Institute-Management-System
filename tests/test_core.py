"""Business-rule and security tests (tenant isolation, finance, results, uploads, backup)."""
import io

import pytest
from PIL import Image

from ims import accounts, backup, branding, db, exams, fees, people
from ims.actor import Actor, PermissionDenied
from ims.db import Tenant, TenantError


def actor_for(env, kind, username_prefix=None):
    info = env[kind]
    if not username_prefix:
        return Actor.load(info["uid"])
    u = db.query_one("SELECT id FROM users WHERE username=?", (f"{username_prefix}{info['iid']}",))
    return Actor.load(u["id"])


# ---------------------------------------------------------------- onboarding
def test_blank_name_rejected(env):
    with pytest.raises(accounts.ValidationError, match="blank"):
        accounts.validate_institution_name("   ")


def test_duplicate_username_rejected(env):
    with pytest.raises(accounts.ValidationError):
        accounts.create_workspace(institution_type="school", name="Dup School", logo_png=None, admin_name="X",
                                  username="owner0", email="", password="Secret123", session_key="dup")


def test_weak_password_rejected(env):
    with pytest.raises(accounts.ValidationError, match="Password"):
        accounts.create_workspace(institution_type="school", name="Weak School", logo_png=None, admin_name="X",
                                  username="weakling", email="", password="short", session_key="weak")


def test_signup_rate_limit(env):
    for i in range(accounts.SIGNUPS_PER_SESSION_PER_HOUR):
        accounts.create_workspace(institution_type="college", name=f"Rate College {i}", logo_png=None, admin_name="X",
                                  username=f"rate{i}", email="", password="Secret123", session_key="same-session")
    with pytest.raises(accounts.ValidationError, match="recently"):
        accounts.create_workspace(institution_type="college", name="Rate College X", logo_png=None, admin_name="X",
                                  username="ratex", email="", password="Secret123", session_key="same-session")


def test_login_lockout(env):
    for _ in range(accounts.MAX_FAILED_LOGINS):
        user, _ = accounts.authenticate("owner2", "wrong-password")
        assert user is None
    user, msg = accounts.authenticate("owner2", "Secret123")
    assert user is None and "Too many" in msg
    db.execute("UPDATE users SET locked_until=NULL, failed_attempts=0 WHERE username='owner2'")
    user, _ = accounts.authenticate("owner2", "Secret123")
    assert user is not None


def test_instant_demo_creates_seeded_workspace(env):
    from ims import demo
    uid, username, password, logins = demo.instant_demo("university", "instant-demo-session")
    user, _ = accounts.authenticate(username, password)
    assert user and user["id"] == uid and user["is_owner"]
    t = Tenant(user["institution_id"])
    assert t.count("students") > 0 and t.count("invoices") > 0 and len(logins) == 6


def test_clear_demo_data_keeps_owner_and_isolation(env):
    from ims import demo
    uid, username, password, _ = demo.instant_demo("school", "clear-test-session")
    owner = Actor.load(uid)
    other_before = Tenant(env["college"]["iid"]).count("students")
    assert demo.has_demo_data(owner.inst)
    with pytest.raises(PermissionError):
        teacher = db.query_one("SELECT id FROM users WHERE institution_id=? AND role='teacher'", (owner.iid,))
        demo.clear_institution_data(Actor.load(teacher["id"]))
    demo.clear_institution_data(owner)
    t = owner.tenant
    assert t.count("students") == 0 and t.count("invoices") == 0 and t.count("users") == 1
    assert accounts.authenticate(username, password)[0] is not None
    assert not demo.has_demo_data(Actor.load(uid).inst)
    assert Tenant(env["college"]["iid"]).count("students") == other_before  # other institutions untouched


# ---------------------------------------------------------------- logo validation
def _png(size=(64, 64)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, "PNG")
    return buf.getvalue()


def test_logo_valid_and_invalid():
    assert branding.validate_logo("logo.png", _png()).startswith(b"\x89PNG")
    with pytest.raises(branding.UploadError):
        branding.validate_logo("logo.gif", _png())
    with pytest.raises(branding.UploadError):
        branding.validate_logo("logo.png", b"<?php echo 1; ?>" * 10)
    with pytest.raises(branding.UploadError):
        branding.validate_logo("logo.png", b"x" * (branding.MAX_LOGO_BYTES + 1))


def test_monogram_when_no_logo(env):
    inst = db.query_one("SELECT * FROM institutions WHERE id=?", (env["school"]["iid"],))
    assert inst["logo_path"] is None
    assert branding.logo_bytes(inst).startswith(b"\x89PNG")
    assert branding.initials("Bright Future College") == "BF"


def test_cross_tenant_file_read_blocked(env):
    a, b = env["school"]["iid"], env["college"]["iid"]
    path = branding.save_file(a, "logo", _png(), "png")
    assert branding.read_file(a, path)
    assert branding.read_file(b, path) is None
    assert branding.read_file(b, "../../etc/passwd") is None


# ---------------------------------------------------------------- tenant isolation
def test_tenant_cannot_read_other_records(env):
    a = Actor.load(env["school"]["uid"])
    other = Tenant(env["college"]["iid"])
    foreign_student = other.all("students")[0]
    foreign_invoice = other.all("invoices")[0]
    assert a.tenant.get("students", foreign_student["id"]) is None
    assert a.tenant.get("invoices", foreign_invoice["id"]) is None
    with pytest.raises(TenantError):
        a.tenant.update("students", foreign_student["id"], first_name="Hacked")
    with pytest.raises(PermissionDenied):
        fees.invoice(a.tenant, foreign_invoice["id"])
    # cannot attach own record to a foreign class
    foreign_class = other.all("classes")[0]
    with pytest.raises(TenantError):
        a.tenant.insert("students", admission_no="X1", first_name="X", class_id=foreign_class["id"], created_at=db.now())


def test_institution_id_cannot_be_overridden(env):
    a = Actor.load(env["school"]["uid"])
    nid = a.tenant.insert("notices", title="t", body="b", institution_id=env["college"]["iid"], created_at=db.now())
    assert db.query_one("SELECT institution_id FROM notices WHERE id=?", (nid,))["institution_id"] == a.iid


def test_scoped_sql_requires_filter(env):
    with pytest.raises(TenantError):
        Tenant(env["school"]["iid"]).q("SELECT * FROM students")


def test_backup_rejects_foreign_rows(env):
    raw = backup.create_backup(env["school"]["iid"])
    manifest, data, _ = backup.read_backup(raw)
    data["tables"]["students"][0]["class_id"] = Tenant(env["college"]["iid"]).all("classes")[0]["id"]
    with pytest.raises(accounts.ValidationError):
        backup.validate(manifest, data)


def test_backup_restore_roundtrip(env):
    iid = env["university"]["iid"]
    t = Tenant(iid)
    before = (t.count("students"), t.count("payments"), t.count("results"))
    raw = backup.create_backup(iid)
    backup.restore(raw, expected_iid=iid)
    assert (t.count("students"), t.count("payments"), t.count("results")) == before
    with pytest.raises(accounts.ValidationError):
        backup.restore(raw, expected_iid=env["school"]["iid"])
    with pytest.raises(accounts.ValidationError):
        backup.restore(raw[:-20] + b"0" * 20)


# ---------------------------------------------------------------- roles
def test_accountant_cannot_change_marks(env):
    acc = actor_for(env, "school", "accountant")
    ms = acc.tenant.all("marksheets", "status='draft'") or acc.tenant.all("marksheets")
    with pytest.raises(PermissionDenied):
        exams.save_marks(acc, ms[0]["id"], [])


def test_teacher_cannot_record_payments_or_see_other_classes(env):
    t = actor_for(env, "school", "teacher")
    inv = fees.invoices(t.tenant)[0]
    with pytest.raises(PermissionDenied):
        fees.record_payment(t, inv["id"], 10, "Cash", db.today())
    scope = t.class_scope()
    assert scope is not None and len(scope) < t.tenant.count("classes")


def test_portal_sees_only_linked_student(env):
    p = actor_for(env, "school", "parent")
    s = actor_for(env, "school", "student")
    assert p.portal_student_ids() and s.portal_student_ids() == [s.user["linked_student_id"]]
    assert not p.can("students.view") and not p.can("fees.view")


def test_only_owner_creates_admins(env):
    owner = Actor.load(env["college"]["uid"])
    uid = accounts.create_user(owner, full_name="Admin Two", username="admin2x", email="", role="admin", password="Secret123")
    admin = Actor.load(uid)
    with pytest.raises(PermissionDenied):
        accounts.create_user(admin, full_name="Admin Three", username="admin3x", email="", role="admin", password="Secret123")
    with pytest.raises(PermissionDenied):
        accounts.update_user(admin, owner.uid, full_name="x", email="", role="admin", is_active=False)


# ---------------------------------------------------------------- finance
def test_partial_payment_balance_receipt_reversal(env):
    a = Actor.load(env["college"]["uid"])
    s = a.tenant.all("students", "status='active'")[5]
    inv_id = fees.create_invoice(a, s["id"], [{"description": "Lab fee", "amount": 1000}], db.today(), db.today(),
                                 apply_scholarships=False)
    r1 = fees.record_payment(a, inv_id, 400, "Cash", db.today())
    assert fees.invoice(a.tenant, inv_id)["balance"] == 600 and fees.invoice(a.tenant, inv_id)["state"] == "partial"
    with pytest.raises(accounts.ValidationError):
        fees.record_payment(a, inv_id, 700, "Cash", db.today())
    r2 = fees.record_payment(a, inv_id, 700, "Cash", db.today(), excess_to_credit=True)
    assert r2["credit"] == 100 and fees.invoice(a.tenant, inv_id)["state"] == "paid"
    assert r1["receipt_no"] != r2["receipt_no"]
    with pytest.raises(accounts.ValidationError):
        fees.cancel_invoice(a, inv_id, "mistake entry")
    fees.reverse_payment(a, r2["payment_id"], "Wrong amount")
    assert fees.invoice(a.tenant, inv_id)["balance"] == 600
    assert fees.credit_balance(a.tenant, s["id"]) >= 0
    with pytest.raises(accounts.ValidationError):
        fees.reverse_payment(a, r2["payment_id"], "again please")
    assert db.scalar("SELECT COUNT(*) FROM payments WHERE invoice_id=?", (inv_id,)) == 3  # nothing deleted


def test_discount_threshold_needs_approval(env):
    owner = Actor.load(env["college"]["uid"])
    acc = actor_for(env, "college", "accountant")
    s = owner.tenant.all("students", "status='active'")[6]
    inv_id = fees.create_invoice(owner, s["id"], [{"description": "Tuition", "amount": 1000}], db.today(), db.today(),
                                 apply_scholarships=False)
    assert fees.request_discount(acc, inv_id, 100, "Sibling discount") == "applied"
    assert fees.request_discount(acc, inv_id, 500, "Hardship case") == "pending"
    req = owner.tenant.one("discount_requests", "invoice_id=? AND status='pending'", (inv_id,))
    principal = actor_for(env, "college", "principal")
    fees.decide_discount(principal, req["id"], True)
    assert fees.invoice(owner.tenant, inv_id)["balance"] == 400


def test_scholarship_applied_to_invoice(env):
    a = Actor.load(env["school"]["uid"])
    sch = a.tenant.all("scholarships")[0]
    inv = fees.invoices(a.tenant, "i.student_id=:s", {"s": sch["student_id"]})[0]
    items = a.tenant.all("invoice_items", "invoice_id=? AND item_type='scholarship'", (inv["id"],))
    assert items and abs(items[0]["amount"]) == pytest.approx(inv["gross"] * 0.5)


# ---------------------------------------------------------------- results
def test_grading_and_gpa():
    scale = [{"min": 85, "grade": "A", "point": 4.0}, {"min": 50, "grade": "D", "point": 1.0}, {"min": 0, "grade": "F", "point": 0}]
    assert exams.grade_for(90, scale) == ("A", 4.0)
    assert exams.grade_for(49.99, scale) == ("F", 0)
    lines = [{"point": 4.0, "credit_hours": 3}, {"point": 1.0, "credit_hours": 1}]
    assert exams.gpa(lines) == 3.25


def test_workflow_and_locking(env):
    owner = Actor.load(env["university"]["uid"])
    ms = owner.tenant.one("marksheets", "status='submitted'")
    teacher = actor_for(env, "university", "teacher")
    with pytest.raises(PermissionDenied):
        exams.transition(teacher, ms["id"], "approve")
    with pytest.raises(accounts.ValidationError):
        exams.save_marks(owner, ms["id"], [])  # locked once submitted
    exams.transition(owner, ms["id"], "review")
    exams.transition(owner, ms["id"], "approve")
    exams.transition(owner, ms["id"], "publish")
    res = owner.tenant.one("results", "marksheet_id=?", (ms["id"],))
    with pytest.raises(accounts.ValidationError):
        exams.correct_result(owner, res["id"], 50, False, "")
    exams.correct_result(owner, res["id"], 55, False, "Re-totalling error")
    assert owner.tenant.get("results", res["id"])["obtained_marks"] == 55
    assert owner.tenant.count("result_corrections", "result_id=?", (res["id"],)) == 1


def test_unpublished_results_hidden(env):
    owner = Actor.load(env["university"]["uid"])
    ms = owner.tenant.one("marksheets", "status IN ('draft','reviewed')")
    sid = owner.tenant.one("results", "marksheet_id=?", (ms["id"],))["student_id"]
    exam = owner.tenant.get("exams", ms["exam_id"])
    rep = exams.term_report(owner.tenant, owner.settings, sid, exam["term_id"], published_only=True)
    assert ms["subject_id"] not in [l["subject_id"] for l in rep["lines"]]


def test_csv_import_preview(env):
    a = Actor.load(env["school"]["uid"])
    cls = a.tenant.all("classes")[0]
    csv = ("first_name,last_name,dob,class,section,gender\n"
           f"Ali,Test,2013-01-01,{cls['name']},{cls['section']},Male\n"
           ",NoFirst,2013-01-01,,,\n"
           "Bad,Date,13/01/2013,Nope,Z,Robot\n").encode()
    df = people.preview_import(a, csv)
    assert df["errors"].tolist()[0] == ""
    assert "first_name is required" in df["errors"].tolist()[1]
    assert "dob" in df["errors"].tolist()[2] and "class" in df["errors"].tolist()[2]
    assert people.commit_import(a, df) == 1
