from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ims import fees, pdf, people, reports, session, ui, widgets
from ims.fees import FREQUENCIES, PAYMENT_METHODS

a = session.require("fees.view", "payments.record")
T, S, P = a.tenant, a.settings, a.profile
cur = S["currency"]
ui.page_header("Fees & payments", "Invoices, receipts, partial payments, advance credit, discounts, scholarships and late fees", tips=[
    "**Collect & manage**: search for a student. Their unpaid invoice opens first, so enter the amount and press **Record payment**.",
    "Every payment gets a receipt number and a PDF receipt. Partial payments are fine.",
    "Wrong entry? Use **Reverse** on that payment. Payments are never deleted, so the history stays traceable.",
    "**Generate invoices** bills a whole class from the fee structure. Students already billed for the same period are skipped.",
    "Set up **Fee setup** first (fee types and amounts per class or program)."])

open_inv = [i for i in fees.invoices(T, "i.status='issued'") if i["balance"] > fees.EPS]
m = st.container(horizontal=True)
today_coll = T.scalar("SELECT IFNULL(SUM(amount),0) AS v FROM payments WHERE institution_id=:iid AND kind<>'credit_applied' "
                      "AND payment_date=:d", {"d": date.today().isoformat()})
m.metric("Collected today", ui.money(today_coll, S), icon=":material/today:", width="stretch")
m.metric("Outstanding", ui.money(sum(i["balance"] for i in open_inv), S), icon=":material/account_balance_wallet:", width="stretch")
m.metric("Overdue invoices", sum(1 for i in open_inv if i["overdue_days"]), icon=":material/schedule:", width="stretch")
m.metric("Pending discounts", T.count("discount_requests", "status='pending'"), icon=":material/percent:", width="stretch")

names = ["Collect & manage", "All invoices"]
if a.can("fees.manage"):
    names += ["Generate invoices", "Fee setup", "Late fees"]
if a.can("scholarships.manage"):
    names.append("Scholarships")
if a.can("payments.reverse", "payments.record"):
    names.append("Advance credit & refunds")
tabs = dict(zip(names, st.tabs(names)))


def class_name(student):
    return people.class_label(T.get("classes", student["class_id"]))


with tabs["Collect & manage"]:
    due_only = st.toggle("Only students with an unpaid balance", value=True, key="due_only")
    if due_only:
        owing = {}
        for i in open_inv:
            owing[i["student_id"]] = owing.get(i["student_id"], 0) + i["balance"]
        rows = [T.get("students", sid) for sid in owing]
        opts = {r["id"]: f"{people.full_name(r)} · {r['admission_no']} · owes {ui.money(owing[r['id']], S)}"
                for r in sorted(rows, key=lambda r: -owing[r["id"]])}
        if not opts:
            st.success("Nobody has an unpaid balance.", icon=":material/verified:")
            s = None
        else:
            pick = st.selectbox("Student", list(opts), format_func=opts.get, index=None, key="fee_student_due",
                                placeholder=f"{len(opts)} student(s) owe fees — search or pick one")
            s = T.get("students", pick) if pick else None
    else:
        s = widgets.pick_student(a, "fee_student", statuses=("active", "on_leave", "graduated", "withdrawn", "transferred"), scoped=False)
    if s:
        invs = fees.invoices(T, "i.student_id=:s", {"s": s["id"]})
        credit = fees.credit_balance(T, s["id"])
        c = st.container(horizontal=True)
        c.metric("Balance due", ui.money(sum(i["balance"] for i in invs if i["state"] != "cancelled"), S), width="stretch")
        c.metric("Advance credit", ui.money(credit, S), width="stretch")
        c.metric("Invoices", len(invs), width="stretch")
        if not invs:
            widgets.empty("No invoices for this student.")
        else:
            df = pd.DataFrame(invs)
            df["status"] = df["state"].map(lambda x: x.title())
            st.dataframe(df[["invoice_no", "period_label", "issue_date", "due_date", "total", "paid", "balance", "status", "overdue_days"]],
                         hide_index=True, column_config={k: st.column_config.NumberColumn(format="%.2f") for k in ("total", "paid", "balance")})
            iopts = {i["id"]: f"{i['invoice_no']} · {i['period_label'] or ''} · balance {i['balance']:,.2f} · {i['state']}" for i in invs}
            unpaid_first = sorted(invs, key=lambda i: (i["balance"] <= fees.EPS, i["issue_date"]))
            iid = st.selectbox("Invoice", list(iopts), format_func=iopts.get, index=list(iopts).index(unpaid_first[0]["id"]))
            inv = fees.invoice(T, iid)
            left, right = st.columns([3, 2], gap="medium")
            with left, st.container(border=True):
                st.markdown(f"#### {inv['invoice_no']} {ui.badge_md(inv['state'])}"
                            + (f" :red-badge[{inv['overdue_days']} days overdue]" if inv["overdue_days"] else ""))
                items = T.all("invoice_items", "invoice_id=?", (iid,))
                st.dataframe(pd.DataFrame(items)[["description", "item_type", "amount"]], hide_index=True)
                st.markdown(f"Total **{ui.money(inv['total'], S)}** · Paid **{ui.money(inv['paid'], S)}** · "
                            f"Balance **{ui.money(inv['balance'], S)}**")
                st.download_button("Invoice PDF", lambda: pdf.invoice_pdf(T, a.inst, S, inv, s, class_name(s)),
                                   f"{inv['invoice_no']}.pdf", "application/pdf", icon=":material/picture_as_pdf:", on_click="ignore")
                pays = T.q("SELECT p.*, u.full_name AS by_user FROM payments p LEFT JOIN users u ON u.id=p.recorded_by "
                           "WHERE p.institution_id=:iid AND p.invoice_id=:i ORDER BY p.id", {"i": iid})
                if pays:
                    st.markdown("**Payments**")
                    for p_ in pays:
                        x1, x2, x3 = st.columns([3, 1, 1], vertical_alignment="center")
                        tag = " :gray-badge[reversed]" if p_["is_reversed"] else (" :red-badge[reversal]" if p_["kind"] == "reversal" else "")
                        x1.markdown(f"`{p_['receipt_no']}` {ui.fmt_date(p_['payment_date'], S)} · {p_['method']} · "
                                    f"**{ui.money(p_['amount'], S)}**{tag}")
                        x2.download_button("Receipt", lambda p_=p_: pdf.receipt_pdf(T, a.inst, S, T.get("payments", p_["id"]),
                                                                                     fees.invoice(T, iid), s, p_["by_user"] or ""),
                                           f"{p_['receipt_no']}.pdf", "application/pdf", key=f"rc_{p_['id']}", on_click="ignore",
                                           icon=":material/receipt_long:")
                        if a.can("payments.reverse") and p_["kind"] != "reversal" and not p_["is_reversed"]:
                            with x3.popover("Reverse", icon=":material/undo:"):
                                reason = st.text_input("Reason *", key=f"rv_{p_['id']}")
                                if st.button("Confirm reversal", key=f"rvb_{p_['id']}", type="primary"):
                                    session.attempt(fees.reverse_payment, a, p_["id"], reason, success="Payment reversed.", rerun=True)
            with right:
                if inv["state"] not in ("paid", "cancelled") and a.can("payments.record"):
                    with st.container(border=True):
                        st.markdown("**Record payment**")
                        with st.form(f"pay_{iid}"):
                            amt = st.number_input(f"Amount ({cur})", min_value=0.0, value=float(inv["balance"]), step=100.0)
                            x1, x2 = st.columns(2)
                            method = x1.selectbox("Method", PAYMENT_METHODS)
                            pday = x2.date_input("Date", date.today(), max_value=date.today())
                            ref = st.text_input("Reference / cheque / transaction no")
                            extra = st.checkbox("Keep any extra as advance credit")
                            if st.form_submit_button("Record payment", type="primary", icon=":material/point_of_sale:"):
                                res = session.attempt(fees.record_payment, a, iid, amt, method, pday.isoformat(), ref, extra)
                                if res:
                                    session.flash(f"Receipt {res['receipt_no']} recorded." + (f" {ui.money(res['credit'], S)} kept as credit." if res["credit"] else ""))
                                    st.rerun()
                        if credit > fees.EPS:
                            amt_c = st.number_input("Apply advance credit", 0.0, float(min(credit, inv["balance"])),
                                                    float(min(credit, inv["balance"])), key=f"cr_{iid}")
                            if st.button("Apply credit", icon=":material/redeem:"):
                                session.attempt(fees.apply_credit, a, iid, amt_c, success="Credit applied.", rerun=True)
                if inv["state"] not in ("paid", "cancelled") and a.can("fees.manage", "discounts.approve"):
                    with st.expander("Discount / waiver", icon=":material/percent:"):
                        st.caption(f"Discounts above {S['discount_approval_percent']}% of fees need principal approval.")
                        d_amt = st.number_input("Amount", 0.0, float(inv["balance"]), 0.0, key=f"da_{iid}")
                        d_reason = st.text_input("Reason *", key=f"dr_{iid}")
                        if st.button("Apply / request discount", key=f"db_{iid}"):
                            res = session.attempt(fees.request_discount, a, iid, d_amt, d_reason)
                            if res:
                                session.flash("Discount applied." if res == "applied" else "Discount sent for approval.")
                                st.rerun()
                if inv["status"] != "cancelled" and a.can("fees.manage"):
                    with st.expander("Cancel invoice", icon=":material/block:"):
                        c_reason = st.text_input("Reason *", key=f"cx_{iid}")
                        if st.button("Cancel invoice", key=f"cxb_{iid}"):
                            session.attempt(fees.cancel_invoice, a, iid, c_reason, success="Invoice cancelled.", rerun=True)

with tabs["All invoices"]:
    c1, c2, c3 = st.columns(3)
    start = c1.date_input("Issued from", date.today() - timedelta(days=365), key="ai_from")
    end = c2.date_input("to", date.today() + timedelta(days=365), key="ai_to")
    states = c3.multiselect("Status", ["unpaid", "partial", "paid", "cancelled"], default=["unpaid", "partial"])
    df = reports.invoice_list(a, {"start": start.isoformat(), "end": end.isoformat()})
    if not df.empty and states:
        df = df[df["Status"].isin(states)]
    st.dataframe(df, hide_index=True)
    widgets.export_buttons(a, "Invoices", df, "inv_exp")

if "Generate invoices" in tabs:
    with tabs["Generate invoices"]:
        mode = st.segmented_control("Mode", ["Bulk from fee structure", "Single custom invoice"], default="Bulk from fee structure")
        if mode == "Bulk from fee structure":
            cid = widgets.pick_class(a, "gen_cls", scoped=False)
            if cid:
                cls = T.get("classes", cid)
                structs = T.q("""SELECT fs.*, ft.name FROM fee_structures fs JOIN fee_types ft ON ft.id=fs.fee_type_id
                                 WHERE fs.institution_id=:iid AND (fs.class_id=:c OR (fs.class_id IS NULL AND (fs.program_id=:p OR fs.program_id IS NULL)))""",
                              {"c": cid, "p": cls["program_id"] or -1})
                if not structs:
                    widgets.empty("No fee structure for this class yet. Add one in Fee setup.")
                else:
                    sopts = {x["id"]: f"{x['name']} · {ui.money(x['amount'], S)} · {x['frequency']}" for x in structs}
                    chosen = st.multiselect("Fees to include", list(sopts), default=list(sopts), format_func=sopts.get)
                    c1, c2, c3 = st.columns(3)
                    period = c1.text_input("Period label *", f"{date.today():%B %Y}")
                    issue = c2.date_input("Issue date", date.today())
                    due = c3.date_input("Due date", date.today() + timedelta(days=15))
                    studs = T.all("students", "class_id=? AND status='active'", (cid,))
                    st.caption(f"{len(studs)} active student(s). Active scholarships are applied automatically. "
                               "Students who already have an invoice for this period are skipped.")
                    if st.button(f"Generate {len(studs)} invoice(s)", type="primary", icon=":material/receipt:"):
                        res = session.attempt(fees.bulk_generate, a, [x["id"] for x in studs], chosen, issue.isoformat(),
                                              due.isoformat(), period)
                        if res:
                            session.flash(f"{res[0]} invoice(s) created, {len(res[1])} skipped.")
                            st.rerun()
        else:
            s = widgets.pick_student(a, "gen_student", scoped=False)
            ftypes = widgets.lookup(a, "fee_types")
            if s and ftypes:
                base = pd.DataFrame({"fee_type_id": [next(iter(ftypes))], "description": [next(iter(ftypes.values()))], "amount": [1000.0]})
                ed = st.data_editor(base, num_rows="dynamic", hide_index=True, key="custom_items", column_config={
                    "fee_type_id": st.column_config.SelectboxColumn("Fee type", options=list(ftypes), format_func=ftypes.get),
                    "amount": st.column_config.NumberColumn(min_value=0.01, format="%.2f")})
                c1, c2, c3 = st.columns(3)
                period = c1.text_input("Period label", key="ci_period")
                issue = c2.date_input("Issue date", date.today(), key="ci_issue")
                due = c3.date_input("Due date", date.today() + timedelta(days=15), key="ci_due")
                notes = st.text_input("Notes")
                if st.button("Create invoice", type="primary", icon=":material/receipt:"):
                    items = [{"fee_type_id": int(r.fee_type_id) if pd.notna(r.fee_type_id) else None,
                              "description": str(r.description or ""), "amount": float(r.amount or 0)} for r in ed.itertuples()]
                    if session.attempt(fees.create_invoice, a, s["id"], items, issue.isoformat(), due.isoformat(), period, notes,
                                       success="Invoice created."):
                        st.rerun()
            elif not ftypes:
                widgets.empty("Add fee types in Fee setup first.")

if "Fee setup" in tabs:
    with tabs["Fee setup"]:
        c1, c2 = st.columns([1, 2])
        with c1, st.container(border=True):
            st.markdown("**Fee types**")
            for f in T.all("fee_types", order="name"):
                st.markdown(f"- {f['name']}")
            with st.form("ft", clear_on_submit=True):
                name = st.selectbox("Name", P["fee_examples"] + ["Other…"], accept_new_options=True)
                if st.form_submit_button("Add fee type", icon=":material/add:") and name and name != "Other…":
                    if T.one("fee_types", "lower(name)=lower(?)", (name,)):
                        st.error("That fee type exists.")
                    else:
                        T.insert("fee_types", name=name.strip(), category="General")
                        st.rerun()
        with c2, st.container(border=True):
            st.markdown("**Fee structure** · amounts by class, program, semester or category")
            rows = T.q("""SELECT fs.id, ft.name AS fee, fs.amount, fs.frequency, c.name || IFNULL(' – ' || NULLIF(c.section,''),'') AS class,
                          p.name AS program, fs.semester_no, fs.student_category, y.name AS year FROM fee_structures fs
                          JOIN fee_types ft ON ft.id=fs.fee_type_id LEFT JOIN classes c ON c.id=fs.class_id
                          LEFT JOIN programs p ON p.id=fs.program_id LEFT JOIN academic_years y ON y.id=fs.academic_year_id
                          WHERE fs.institution_id=:iid ORDER BY class, ft.name""")
            if rows:
                st.dataframe(pd.DataFrame(rows).drop(columns="id"), hide_index=True)
            ftypes = widgets.lookup(a, "fee_types")
            copts = people.class_options(a, only_scope=False)
            progs = widgets.lookup(a, "programs")
            years = widgets.lookup(a, "academic_years")
            if ftypes:
                with st.form("fs", clear_on_submit=True):
                    x1, x2, x3 = st.columns(3)
                    ft = x1.selectbox("Fee type", list(ftypes), format_func=ftypes.get)
                    amt = x2.number_input(f"Amount ({cur})", 0.01, 1e9, 1000.0, 100.0)
                    freq = x3.selectbox("Frequency", FREQUENCIES, index=2)
                    x1, x2, x3 = st.columns(3)
                    cls = x1.selectbox(P["class"], list(copts), format_func=copts.get, index=None)
                    prog = x2.selectbox(P["program"] or "Program", list(progs), format_func=progs.get, index=None) if progs else None
                    yr = x3.selectbox("Academic year", list(years), format_func=years.get, index=None)
                    cat = st.text_input("Student category (optional)")
                    if st.form_submit_button("Add to fee structure", type="primary", icon=":material/add:"):
                        T.insert("fee_structures", fee_type_id=ft, amount=amt, frequency=freq, class_id=cls, program_id=prog,
                                 academic_year_id=yr, student_category=cat.strip() or None)
                        a.log("fee_structure_added", "fee_structures")
                        st.rerun()

    with tabs["Late fees"]:
        rule = (f"{ui.money(S['late_fee_amount'], S)} per day" if S["late_fee_type"] == "per_day"
                else f"{ui.money(S['late_fee_amount'], S)} flat") + f" after {S['late_fee_grace_days']} grace day(s)"
        st.markdown(f"Current rule: **{rule}** (change it in Settings → Finance).")
        preview = [(i, fees.late_fee_for(i, S, date.today())) for i in fees.invoices(T, "i.status='issued' AND i.due_date < :d",
                                                                                      {"d": date.today().isoformat()})]
        preview = [(i, f) for i, f in preview if f > 0]
        if preview:
            st.dataframe(pd.DataFrame([{"Invoice": i["invoice_no"], "Student": i["student"], "Days overdue": i["overdue_days"],
                                        "Late fee": f} for i, f in preview]), hide_index=True)
            if st.button(f"Apply late fee to {len(preview)} invoice(s)", type="primary"):
                session.attempt(fees.apply_late_fees, a, success="Late fees applied.", rerun=True)
        else:
            widgets.empty("No late fees are due.")

if "Scholarships" in tabs:
    with tabs["Scholarships"]:
        rows = T.q("""SELECT sc.name, st.first_name || ' ' || IFNULL(st.last_name,'') AS student, sc.discount_type, sc.value,
                      sc.effective_from, sc.effective_to, sc.status, sc.eligibility, u.full_name AS approved_by
                      FROM scholarships sc JOIN students st ON st.id=sc.student_id LEFT JOIN users u ON u.id=sc.approved_by
                      WHERE sc.institution_id=:iid ORDER BY sc.created_at DESC""")
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True)
        s = widgets.pick_student(a, "sch_student", scoped=False)
        if s:
            with st.form("sch", clear_on_submit=True):
                x1, x2, x3 = st.columns(3)
                name = x1.text_input("Scholarship / aid name", "Merit scholarship")
                typ = x2.selectbox("Type", ["percent", "fixed"])
                val = x3.number_input("Value", 0.01, 1e9, 25.0)
                x1, x2 = st.columns(2)
                f_, t_ = x1.date_input("Effective from", date.today()), x2.date_input("Effective to", date.today() + timedelta(days=365))
                elig = st.text_input("Eligibility / basis")
                if st.form_submit_button("Approve scholarship", type="primary", icon=":material/workspace_premium:"):
                    if typ == "percent" and val > 100:
                        st.error("A percentage cannot exceed 100.")
                    elif t_ < f_:
                        st.error("End date is before start date.")
                    else:
                        T.insert("scholarships", student_id=s["id"], name=name, discount_type=typ, value=val,
                                 effective_from=f_.isoformat(), effective_to=t_.isoformat(), eligibility=elig,
                                 approved_by=a.uid, created_at=fees.db.now())
                        a.log("scholarship_approved", "student", s["id"], {"value": val, "type": typ})
                        session.flash("Scholarship recorded. It applies to new invoices automatically.")
                        st.rerun()

if "Advance credit & refunds" in tabs:
    with tabs["Advance credit & refunds"]:
        rows = T.q("""SELECT st.id, st.admission_no, st.first_name || ' ' || IFNULL(st.last_name,'') AS student, SUM(sc.amount) AS credit
                      FROM student_credits sc JOIN students st ON st.id=sc.student_id WHERE sc.institution_id=:iid
                      GROUP BY st.id HAVING SUM(sc.amount) > 0.005""")
        if rows:
            st.dataframe(pd.DataFrame(rows).drop(columns="id"), hide_index=True)
            if a.can("payments.reverse"):
                opts = {r["id"]: f"{r['student']} · credit {r['credit']:,.2f}" for r in rows}
                with st.form("refund"):
                    sid = st.selectbox("Student", list(opts), format_func=opts.get)
                    x1, x2 = st.columns(2)
                    amt = x1.number_input("Refund amount", 0.01, 1e9, 100.0)
                    method = x2.selectbox("Method", PAYMENT_METHODS)
                    reason = st.text_input("Reason *")
                    if st.form_submit_button("Record refund", type="primary", icon=":material/currency_exchange:"):
                        session.attempt(fees.refund_credit, a, sid, amt, method, reason, success="Refund recorded.", rerun=True)
        else:
            widgets.empty("No student has advance credit.")
