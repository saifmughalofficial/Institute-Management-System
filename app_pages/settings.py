import json

import pandas as pd
import streamlit as st

from ims import accounts, branding, db, demo, exams, session, ui
from ims.attendance import DAYS
from ims.profiles import ACCENTS, CURRENCIES, DATE_FORMATS, OPTIONAL_MODULES, PROFILES

a = session.require("settings.manage")
T, S, P = a.tenant, a.settings, a.profile
inst = a.inst
ui.page_header("Settings", f"Branding, academic rules, finance rules and modules for {inst['name']}")


def save_settings(new: dict, note: str):
    db.execute("UPDATE institutions SET settings_json=? WHERE id=?", (json.dumps(new), a.iid))
    a.log("settings_changed", "institution", a.iid, {"section": note})
    session.flash("Settings saved.")
    st.rerun()


t = st.tabs(["Branding & profile", "Academic rules", "Finance rules", "Modules & leave"] +
             (["Danger zone"] if a.user["is_owner"] else []))
if a.user["is_owner"]:
    with t[4], st.container(border=True):
        st.markdown("**Clear all institution data**")
        st.write("Deletes every student, guardian, staff record, class, subject, attendance, invoice, payment, result, notice "
                 "and every login except yours. Use it to remove demo data or start over. "
                 "Your institution name, logo, settings and owner login are kept. **This cannot be undone. "
                 "Download a backup first.**")
        confirm = st.text_input(f"Type the institution name to confirm: {inst['name']}", key="clear_confirm")
        if st.button("Clear all data", type="primary", icon=":material/delete_forever:",
                     disabled=confirm.strip() != inst["name"]):
            n = demo.clear_institution_data(a)
            session.flash(f"All data cleared ({n} records removed).")
            st.rerun()
with t[0]:
    c1, c2 = st.columns([2, 1], gap="large")
    with c1, st.form("brand"):
        name = st.text_input("Institution name", inst["name"])
        x1, x2 = st.columns(2)
        motto = x1.text_input("Motto", inst["motto"] or "")
        website = x2.text_input("Website", inst["website"] or "")
        address = st.text_input("Address", inst["address"] or "")
        x1, x2 = st.columns(2)
        phone = x1.text_input("Phone", inst["phone"] or "")
        email = x2.text_input("Email", inst["email"] or "")
        x1, x2 = st.columns(2)
        accent = x1.selectbox("Brand colour", list(ACCENTS), index=list(ACCENTS).index(S["accent"]))
        fmt_keys = list(DATE_FORMATS)
        fmt = x2.selectbox("Date format", fmt_keys, index=list(DATE_FORMATS.values()).index(S["date_format"])
                           if S["date_format"] in DATE_FORMATS.values() else 0)
        st.caption(f"Institution type: **{PROFILES[inst['institution_type']]['title']}** (fixed after setup)")
        if st.form_submit_button("Save profile", type="primary", icon=":material/save:"):
            try:
                clean = accounts.validate_institution_name(name)
                db.execute("UPDATE institutions SET name=?, motto=?, website=?, address=?, phone=?, email=? WHERE id=?",
                           (clean, motto.strip(), website.strip(), address.strip(), phone.strip(), email.strip(), a.iid))
                save_settings({**S, "accent": accent, "date_format": DATE_FORMATS[fmt]}, "branding")
            except accounts.ValidationError as exc:
                st.error(str(exc))
    with c2, st.container(border=True):
        st.markdown("**Logo**")
        st.image(branding.logo_bytes(inst, S["accent"]), width=140)
        st.caption("Uploaded logo" if inst["logo_path"] else "Default monogram (no logo uploaded)")
        up = st.file_uploader("Upload new logo", type=["png", "jpg", "jpeg", "webp"], max_upload_size=2)
        if up is not None and st.button("Use this logo", type="primary", icon=":material/upload:"):
            try:
                png = branding.validate_logo(up.name, up.getvalue())
                path = branding.save_file(a.iid, "logo", png, "png")
                old = inst["logo_path"]
                db.execute("UPDATE institutions SET logo_path=? WHERE id=?", (path, a.iid))
                branding.delete_file(a.iid, old)
                a.log("logo_changed", "institution", a.iid)
                session.flash("Logo updated.")
                st.rerun()
            except branding.UploadError as exc:
                st.error(str(exc))
        if inst["logo_path"] and st.button("Remove logo", icon=":material/delete:"):
            branding.delete_file(a.iid, inst["logo_path"])
            db.execute("UPDATE institutions SET logo_path=NULL WHERE id=?", (a.iid,))
            a.log("logo_removed", "institution", a.iid)
            st.rerun()

with t[1]:
    st.markdown("**Grading scale**")
    scale = st.data_editor(pd.DataFrame(S["grading_scale"]), num_rows="dynamic", hide_index=True, key="scale",
                           column_config={"min": st.column_config.NumberColumn("Minimum %", min_value=0, max_value=100),
                                          "grade": "Grade", "point": st.column_config.NumberColumn("Grade point", min_value=0, max_value=10)})
    with st.form("acad"):
        x1, x2, x3 = st.columns(3)
        pass_pct = x1.number_input("Pass mark %", 0.0, 100.0, float(S["pass_percent"]))
        gpa_min = x2.number_input("Good-standing minimum GPA", 0.0, 10.0, float(S["standing_min_gpa"]), 0.1)
        thr = x3.number_input("Low-attendance threshold %", 0.0, 100.0, float(S["attendance_threshold"]))
        x1, x2 = st.columns(2)
        days = x1.multiselect("Working days", DAYS, default=S["working_days"])
        periods = x2.number_input("Periods per day", 1, 14, int(S["periods_per_day"]))
        if st.form_submit_button("Save academic rules", type="primary", icon=":material/save:"):
            rows = scale.dropna().to_dict("records")
            try:
                exams.validate_scale(rows)
                if not days:
                    raise accounts.ValidationError("Choose at least one working day.")
                save_settings({**S, "grading_scale": sorted(rows, key=lambda b: -float(b["min"])), "pass_percent": pass_pct,
                               "standing_min_gpa": gpa_min, "attendance_threshold": thr, "working_days": days,
                               "periods_per_day": int(periods)}, "academic")
            except accounts.ValidationError as exc:
                st.error(str(exc))

with t[2], st.form("fin"):
    x1, x2, x3, x4 = st.columns(4)
    currency = x1.selectbox("Currency", CURRENCIES, index=CURRENCIES.index(S["currency"]) if S["currency"] in CURRENCIES else 0)
    inv_p = x2.text_input("Invoice prefix", S["invoice_prefix"])
    rc_p = x3.text_input("Receipt prefix", S["receipt_prefix"])
    adm_p = x4.text_input("Admission no prefix", S["admission_prefix"])
    x1, x2, x3, x4 = st.columns(4)
    lf_type = x1.selectbox("Late fee rule", ["flat", "per_day"], index=["flat", "per_day"].index(S["late_fee_type"]))
    lf_amt = x2.number_input("Late fee amount", 0.0, 1e7, float(S["late_fee_amount"]))
    grace = x3.number_input("Grace days", 0, 90, int(S["late_fee_grace_days"]))
    disc = x4.number_input("Discount approval above %", 0.0, 100.0, float(S["discount_approval_percent"]))
    if st.form_submit_button("Save finance rules", type="primary", icon=":material/save:"):
        prefixes = [inv_p, rc_p, adm_p]
        if any(not p.strip() or not p.strip().replace("-", "").isalnum() for p in prefixes):
            st.error("Prefixes must be letters/numbers and cannot be blank.")
        else:
            save_settings({**S, "currency": currency, "invoice_prefix": inv_p.strip().upper(), "receipt_prefix": rc_p.strip().upper(),
                           "admission_prefix": adm_p.strip().upper(), "late_fee_type": lf_type, "late_fee_amount": lf_amt,
                           "late_fee_grace_days": int(grace), "discount_approval_percent": disc}, "finance")

with t[3], st.form("mods"):
    st.markdown("**Optional modules** · hidden from everyone when switched off")
    cols = st.columns(3)
    mods = {k: cols[i % 3].toggle(v, S["modules"].get(k, False), key=f"mod_{k}") for i, (k, v) in enumerate(OPTIONAL_MODULES.items())}
    st.markdown("**Annual leave allowance (days)**")
    lv = st.data_editor(pd.DataFrame({"Leave type": list(S["leave_allowance"]), "Days": list(S["leave_allowance"].values())}),
                        num_rows="dynamic", hide_index=True, key="leave_ed")
    if st.form_submit_button("Save", type="primary", icon=":material/save:"):
        allowance = {str(r["Leave type"]).strip(): float(r["Days"]) for r in lv.dropna().to_dict("records") if str(r["Leave type"]).strip()}
        if not allowance:
            st.error("Keep at least one leave type.")
        else:
            save_settings({**S, "modules": mods, "leave_allowance": allowance}, "modules")
