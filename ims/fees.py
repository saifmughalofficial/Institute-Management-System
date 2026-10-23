"""Invoices, payments, receipts, advance credit, discounts, scholarships and late fees.

Money is never deleted. Mistakes are fixed with a reversal entry (negative
payment linked to the original), refunds come out of the student's advance
credit, and every sensitive action is permission-checked and audited.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import db
from .accounts import ValidationError
from .actor import Actor, PermissionDenied

EPS = 0.005
PAYMENT_METHODS = ["Cash", "Bank transfer", "Card", "Cheque", "Mobile wallet", "Other"]
FREQUENCIES = ["one-time", "monthly", "term", "semester", "annual"]


def money(value: float, currency: str) -> str:
    return f"{currency} {value:,.2f}"


INVOICE_SQL = """
    SELECT i.*, st.admission_no, st.first_name || ' ' || IFNULL(st.last_name,'') AS student,
           st.class_id, st.program_id,
           IFNULL((SELECT SUM(amount) FROM invoice_items it WHERE it.invoice_id=i.id), 0) AS total,
           IFNULL((SELECT SUM(amount) FROM invoice_items it WHERE it.invoice_id=i.id
                    AND it.item_type IN ('fee','late_fee')), 0) AS gross,
           IFNULL((SELECT SUM(amount) FROM payments p WHERE p.invoice_id=i.id), 0) AS paid
    FROM invoices i JOIN students st ON st.id=i.student_id
    WHERE i.institution_id=:iid
"""


def _decorate(row: dict) -> dict:
    row["total"] = round(row["total"], 2)
    row["paid"] = round(row["paid"], 2)
    row["balance"] = round(row["total"] - row["paid"], 2)
    overdue = 0
    if row["status"] == "cancelled":
        state = "cancelled"
    elif row["balance"] <= EPS:
        state = "paid"
    else:
        state = "partial" if row["paid"] > EPS else "unpaid"
        overdue = max(0, (date.today() - date.fromisoformat(row["due_date"])).days)
    row["state"] = state
    row["overdue_days"] = overdue
    return row


def invoices(T, where: str = "", params: dict | None = None) -> list[dict]:
    sql = INVOICE_SQL + (f" AND ({where})" if where else "") + " ORDER BY i.issue_date DESC, i.id DESC"
    return [_decorate(r) for r in T.q(sql, params or {})]


def invoice(T, invoice_id: int) -> dict:
    rows = T.q(INVOICE_SQL + " AND i.id=:id", {"id": int(invoice_id)})
    if not rows:
        raise PermissionDenied("Invoice not found in this institution.")
    return _decorate(rows[0])


def credit_balance(T, student_id: int) -> float:
    v = T.scalar("SELECT IFNULL(SUM(amount),0) AS v FROM student_credits WHERE institution_id=:iid "
                 "AND student_id=:s", {"s": int(student_id)})
    return round(float(v or 0), 2)


def active_scholarships(T, student_id: int, on: str) -> list[dict]:
    return T.all("scholarships", "student_id=? AND status='active' AND effective_from<=? AND effective_to>=?",
                 (int(student_id), on, on))


# --------------------------------------------------------------------------- #
# Invoices
# --------------------------------------------------------------------------- #
def create_invoice(actor: Actor, student_id: int, items: list[dict], issue_date: str,
                   due_date: str, period_label: str = "", notes: str = "",
                   apply_scholarships: bool = True) -> int:
    """items: [{fee_type_id, description, amount}] with positive amounts."""
    actor.require("fees.manage")
    T = actor.tenant
    student = T.require("students", student_id)
    if student["status"] not in ("active", "on_leave"):
        raise ValidationError(f"{student['first_name']} is not an active student.")
    if not items:
        raise ValidationError("Add at least one fee line.")
    if due_date < issue_date:
        raise ValidationError("The due date cannot be before the issue date.")
    for it in items:
        if float(it["amount"]) <= 0:
            raise ValidationError("Fee amounts must be greater than zero.")
        if not str(it.get("description") or "").strip():
            raise ValidationError("Every fee line needs a description.")
    s = actor.settings
    with db.transaction():
        number = T.next_number("invoice", s["invoice_prefix"], 5)
        inv_id = T.insert("invoices", invoice_no=number, student_id=student_id,
                          period_label=period_label.strip(), issue_date=issue_date,
                          due_date=due_date, notes=notes.strip(), created_by=actor.uid,
                          created_at=db.now())
        gross = 0.0
        for it in items:
            amt = round(float(it["amount"]), 2)
            gross += amt
            T.insert("invoice_items", invoice_id=inv_id, fee_type_id=it.get("fee_type_id"),
                     item_type="fee", description=it["description"].strip(), amount=amt)
        if apply_scholarships:
            remaining = gross
            for sch in active_scholarships(T, student_id, issue_date):
                cut = gross * sch["value"] / 100 if sch["discount_type"] == "percent" else sch["value"]
                cut = round(min(cut, remaining), 2)
                if cut > EPS:
                    remaining -= cut
                    T.insert("invoice_items", invoice_id=inv_id, item_type="scholarship",
                             description=f"Scholarship: {sch['name']}", amount=-cut)
        actor.log("invoice_created", "invoice", inv_id, {"no": number, "gross": gross})
    return inv_id


def structure_items(T, student: dict, structure_ids: list[int]) -> list[dict]:
    items = []
    for sid in structure_ids:
        fs = T.require("fee_structures", sid)
        ft = T.require("fee_types", fs["fee_type_id"])
        items.append({"fee_type_id": ft["id"], "description": ft["name"], "amount": fs["amount"]})
    return items


def bulk_generate(actor: Actor, student_ids: list[int], structure_ids: list[int], issue_date: str,
                  due_date: str, period_label: str) -> tuple[int, list[str]]:
    """One invoice per student. Students who already have a live invoice for the
    same period are skipped so a batch can safely be re-run."""
    actor.require("fees.manage")
    if not period_label.strip():
        raise ValidationError("Give the batch a period label (e.g. 'Term 1 2026') to prevent duplicates.")
    if not structure_ids:
        raise ValidationError("Choose at least one fee from the fee structure.")
    T = actor.tenant
    created, skipped = 0, []
    for sid in student_ids:
        student = T.require("students", sid)
        dup = T.one("invoices", "student_id=? AND period_label=? AND status<>'cancelled'",
                    (sid, period_label.strip()))
        if dup or student["status"] != "active":
            skipped.append(f"{student['first_name']} {student['last_name']}".strip())
            continue
        create_invoice(actor, sid, structure_items(T, student, structure_ids), issue_date,
                       due_date, period_label)
        created += 1
    actor.log("invoices_bulk_generated", "invoice", None,
              {"created": created, "skipped": len(skipped), "period": period_label})
    return created, skipped


def cancel_invoice(actor: Actor, invoice_id: int, reason: str):
    actor.require("fees.manage")
    T = actor.tenant
    inv = invoice(T, invoice_id)
    if inv["status"] == "cancelled":
        raise ValidationError("This invoice is already cancelled.")
    if abs(inv["paid"]) > EPS:
        raise ValidationError("Reverse the payments on this invoice before cancelling it.")
    if len(reason.strip()) < 5:
        raise ValidationError("Give a cancellation reason (at least 5 characters).")
    T.update("invoices", invoice_id, status="cancelled", cancelled_by=actor.uid,
             cancelled_reason=reason.strip())
    actor.log("invoice_cancelled", "invoice", invoice_id, {"reason": reason})


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #
def record_payment(actor: Actor, invoice_id: int, amount: float, method: str, payment_date: str,
                   reference: str = "", excess_to_credit: bool = False) -> dict:
    actor.require("payments.record")
    T = actor.tenant
    inv = invoice(T, invoice_id)
    amount = round(float(amount), 2)
    if inv["status"] == "cancelled":
        raise ValidationError("Cannot take payment on a cancelled invoice.")
    if amount <= 0:
        raise ValidationError("Payment amount must be greater than zero.")
    if inv["balance"] <= EPS:
        raise ValidationError("This invoice is already fully paid.")
    if method not in PAYMENT_METHODS:
        raise ValidationError("Choose a payment method.")
    if payment_date > db.today():
        raise ValidationError("Payment date cannot be in the future.")
    excess = round(amount - inv["balance"], 2)
    if excess > EPS and not excess_to_credit:
        raise ValidationError(f"The amount exceeds the balance by {excess:,.2f}. Tick 'keep the "
                              f"extra as advance credit' or enter a smaller amount.")
    applied = min(amount, inv["balance"])
    s = actor.settings
    with db.transaction():
        receipt = T.next_number("receipt", s["receipt_prefix"], 6)
        pid = T.insert("payments", invoice_id=invoice_id, student_id=inv["student_id"],
                       receipt_no=receipt, kind="payment", amount=applied, method=method,
                       reference=reference.strip(), payment_date=payment_date,
                       recorded_by=actor.uid, created_at=db.now())
        if excess > EPS:
            T.insert("student_credits", student_id=inv["student_id"], amount=excess,
                     kind="overpayment", payment_id=pid, method=method,
                     reason=f"Excess on receipt {receipt}", created_by=actor.uid, created_at=db.now())
        actor.log("payment_recorded", "payment", pid,
                  {"receipt": receipt, "amount": applied, "credit": max(excess, 0), "method": method})
    return {"payment_id": pid, "receipt_no": receipt, "applied": applied, "credit": max(excess, 0.0)}


def apply_credit(actor: Actor, invoice_id: int, amount: float) -> dict:
    actor.require("payments.record")
    T = actor.tenant
    inv = invoice(T, invoice_id)
    amount = round(float(amount), 2)
    available = credit_balance(T, inv["student_id"])
    if inv["status"] == "cancelled":
        raise ValidationError("Cannot apply credit to a cancelled invoice.")
    if amount <= 0 or amount > available + EPS:
        raise ValidationError(f"Amount must be between 0 and the available credit ({available:,.2f}).")
    if amount > inv["balance"] + EPS:
        raise ValidationError("Amount is larger than the invoice balance.")
    s = actor.settings
    with db.transaction():
        receipt = T.next_number("receipt", s["receipt_prefix"], 6)
        pid = T.insert("payments", invoice_id=invoice_id, student_id=inv["student_id"],
                       receipt_no=receipt, kind="credit_applied", amount=amount,
                       method="Advance credit", payment_date=db.today(),
                       recorded_by=actor.uid, created_at=db.now())
        T.insert("student_credits", student_id=inv["student_id"], amount=-amount, kind="applied",
                 payment_id=pid, reason=f"Applied to {inv['invoice_no']}",
                 created_by=actor.uid, created_at=db.now())
        actor.log("credit_applied", "payment", pid, {"amount": amount, "invoice": inv["invoice_no"]})
    return {"payment_id": pid, "receipt_no": receipt}


def reverse_payment(actor: Actor, payment_id: int, reason: str) -> int:
    actor.require("payments.reverse")
    T = actor.tenant
    pay = T.require("payments", payment_id)
    if pay["kind"] == "reversal":
        raise ValidationError("A reversal entry cannot itself be reversed.")
    if pay["is_reversed"]:
        raise ValidationError("This payment has already been reversed.")
    if len(reason.strip()) < 5:
        raise ValidationError("A reversal needs a reason (at least 5 characters).")
    s = actor.settings
    with db.transaction():
        # Undo any advance credit this payment created, if that credit is still unspent.
        created_credit = T.scalar("SELECT IFNULL(SUM(amount),0) AS v FROM student_credits WHERE "
                                  "institution_id=:iid AND payment_id=:p AND kind='overpayment'",
                                  {"p": payment_id}) or 0
        if created_credit > EPS:
            if credit_balance(T, pay["student_id"]) + EPS < created_credit:
                raise ValidationError("The advance credit from this payment has already been used. "
                                      "Reverse the payment that used it first.")
            T.insert("student_credits", student_id=pay["student_id"], amount=-created_credit,
                     kind="adjustment", payment_id=payment_id,
                     reason=f"Reversal of {pay['receipt_no']}", created_by=actor.uid, created_at=db.now())
        number = T.next_number("reversal", s["reversal_prefix"], 6)
        rid = T.insert("payments", invoice_id=pay["invoice_id"], student_id=pay["student_id"],
                       receipt_no=number, kind="reversal", amount=-pay["amount"],
                       method=pay["method"], payment_date=db.today(), reverses_payment_id=payment_id,
                       reason=reason.strip(), recorded_by=actor.uid, created_at=db.now())
        T.update("payments", payment_id, is_reversed=1)
        if pay["kind"] == "credit_applied":
            T.insert("student_credits", student_id=pay["student_id"], amount=pay["amount"],
                     kind="restored", payment_id=rid, reason=f"Reversal of {pay['receipt_no']}",
                     created_by=actor.uid, created_at=db.now())
        actor.log("payment_reversed", "payment", payment_id,
                  {"receipt": pay["receipt_no"], "amount": pay["amount"], "reason": reason})
    return rid


def refund_credit(actor: Actor, student_id: int, amount: float, method: str, reason: str):
    actor.require("payments.reverse")
    T = actor.tenant
    T.require("students", student_id)
    amount = round(float(amount), 2)
    available = credit_balance(T, student_id)
    if amount <= 0 or amount > available + EPS:
        raise ValidationError(f"Refund must be between 0 and the available credit ({available:,.2f}).")
    if len(reason.strip()) < 5:
        raise ValidationError("A refund needs a reason (at least 5 characters).")
    T.insert("student_credits", student_id=student_id, amount=-amount, kind="refund", method=method,
             reason=reason.strip(), created_by=actor.uid, created_at=db.now())
    actor.log("credit_refunded", "student", student_id, {"amount": amount, "reason": reason})


# --------------------------------------------------------------------------- #
# Discounts and late fees
# --------------------------------------------------------------------------- #
def request_discount(actor: Actor, invoice_id: int, amount: float, reason: str) -> str:
    """Apply directly when within the threshold (or the actor can approve);
    otherwise queue for approval. Returns 'applied' or 'pending'."""
    actor.require("fees.manage", "discounts.approve")
    T = actor.tenant
    inv = invoice(T, invoice_id)
    amount = round(float(amount), 2)
    if inv["status"] == "cancelled":
        raise ValidationError("Cannot discount a cancelled invoice.")
    if amount <= 0 or amount > inv["balance"] + EPS:
        raise ValidationError(f"Discount must be between 0 and the balance ({inv['balance']:,.2f}).")
    if len(reason.strip()) < 5:
        raise ValidationError("A discount needs a reason (at least 5 characters).")
    pct = amount / inv["gross"] * 100 if inv["gross"] else 100
    threshold = float(actor.settings["discount_approval_percent"])
    with db.transaction():
        if actor.can("discounts.approve") or pct <= threshold:
            T.insert("invoice_items", invoice_id=invoice_id, item_type="discount",
                     description=f"Discount: {reason.strip()}", amount=-amount)
            actor.log("discount_applied", "invoice", invoice_id, {"amount": amount, "reason": reason})
            return "applied"
        rid = T.insert("discount_requests", invoice_id=invoice_id, amount=amount, reason=reason.strip(),
                       requested_by=actor.uid, created_at=db.now())
        actor.log("discount_requested", "discount_request", rid, {"amount": amount, "percent": round(pct, 1)})
        return "pending"


def decide_discount(actor: Actor, request_id: int, approve: bool):
    actor.require("discounts.approve")
    T = actor.tenant
    req = T.require("discount_requests", request_id)
    if req["status"] != "pending":
        raise ValidationError("This request has already been decided.")
    with db.transaction():
        if approve:
            inv = invoice(T, req["invoice_id"])
            if req["amount"] > inv["balance"] + EPS:
                raise ValidationError("The discount is now larger than the remaining balance.")
            T.insert("invoice_items", invoice_id=req["invoice_id"], item_type="discount",
                     description=f"Discount: {req['reason']}", amount=-req["amount"])
        T.update("discount_requests", request_id, status="approved" if approve else "rejected",
                 decided_by=actor.uid, decided_at=db.now())
        actor.log("discount_approved" if approve else "discount_rejected", "discount_request", request_id)


def late_fee_for(inv: dict, settings: dict, as_of: date) -> float:
    if inv["state"] in ("paid", "cancelled") or inv["late_fee_applied_on"]:
        return 0.0
    days = (as_of - date.fromisoformat(inv["due_date"])).days - int(settings["late_fee_grace_days"])
    amount = float(settings["late_fee_amount"])
    if days <= 0 or amount <= 0:
        return 0.0
    return round(amount * days if settings["late_fee_type"] == "per_day" else amount, 2)


def apply_late_fees(actor: Actor) -> int:
    actor.require("fees.manage")
    T = actor.tenant
    s = actor.settings
    today = date.today()
    n = 0
    with db.transaction():
        for inv in invoices(T, "i.status='issued' AND i.due_date < :d AND i.late_fee_applied_on IS NULL",
                            {"d": today.isoformat()}):
            fee = late_fee_for(inv, s, today)
            if fee > 0:
                T.insert("invoice_items", invoice_id=inv["id"], item_type="late_fee",
                         description=f"Late fee ({inv['overdue_days']} days overdue)", amount=fee)
                T.update("invoices", inv["id"], late_fee_applied_on=today.isoformat())
                n += 1
        actor.log("late_fees_applied", "invoice", None, {"count": n})
    return n


# --------------------------------------------------------------------------- #
# Ledger
# --------------------------------------------------------------------------- #
def student_ledger(T, student_id: int) -> pd.DataFrame:
    rows = []
    for inv in invoices(T, "i.student_id=:s", {"s": int(student_id)}):
        if inv["status"] == "cancelled":
            continue
        rows.append({"Date": inv["issue_date"], "Reference": inv["invoice_no"],
                     "Description": f"Invoice {inv['period_label'] or ''}".strip(),
                     "Debit": inv["total"], "Credit": 0.0})
    pays = T.q("SELECT p.*, i.invoice_no FROM payments p JOIN invoices i ON i.id=p.invoice_id "
               "WHERE p.institution_id=:iid AND p.student_id=:s", {"s": int(student_id)})
    for p in pays:
        label = {"payment": f"Payment ({p['method']})", "credit_applied": "Advance credit applied",
                 "reversal": f"Reversal: {p['reason'] or ''}"}[p["kind"]]
        rows.append({"Date": p["payment_date"], "Reference": p["receipt_no"],
                     "Description": f"{label} → {p['invoice_no']}", "Debit": 0.0, "Credit": p["amount"]})
    if not rows:
        return pd.DataFrame(columns=["Date", "Reference", "Description", "Debit", "Credit", "Balance"])
    df = pd.DataFrame(rows).sort_values(["Date", "Reference"]).reset_index(drop=True)
    df["Balance"] = (df["Debit"] - df["Credit"]).cumsum().round(2)
    return df
