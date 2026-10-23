import pandas as pd
import streamlit as st

from ims import db, session, ui, widgets

a = session.require("assets.manage")
T, S = a.tenant, a.settings
ui.page_header("Inventory & assets", "Equipment register, allocation, condition, maintenance and stock movement")

rows = T.all("assets", order="name")
m = st.container(horizontal=True)
m.metric("Items", sum(r["quantity"] for r in rows), width="stretch")
m.metric("Register value", ui.money(sum((r["value"] or 0) * r["quantity"] for r in rows), S), width="stretch")
m.metric("Needs repair", sum(1 for r in rows if r["condition"] in ("damaged", "needs repair")), width="stretch")

t1, t2, t3 = st.tabs(["Register", "Add item", "Movements"])
with t1:
    if rows:
        df = pd.DataFrame(rows)[["tag", "name", "category", "location", "assigned_to", "condition", "status", "quantity", "value"]]
        st.dataframe(df, hide_index=True)
        widgets.export_buttons(a, "Asset register", df, "as_exp", perm=None)
        opts = {r["id"]: f"{r['tag'] or ''} {r['name']}" for r in rows}
        aid = st.selectbox("Update item", list(opts), format_func=opts.get, index=None)
        if aid:
            r = T.get("assets", aid)
            with st.form(f"upd_{aid}"):
                x1, x2, x3, x4 = st.columns(4)
                loc = x1.text_input("Location", r["location"] or "")
                to = x2.text_input("Assigned to", r["assigned_to"] or "")
                conds = ["new", "good", "fair", "needs repair", "damaged"]
                cond = x3.selectbox("Condition", conds, index=conds.index(r["condition"]) if r["condition"] in conds else 1)
                stats = ["in_stock", "in_use", "under_maintenance", "disposed"]
                stat = x4.selectbox("Status", stats, index=stats.index(r["status"]) if r["status"] in stats else 0)
                note = st.text_input("Movement note")
                if st.form_submit_button("Save", type="primary"):
                    with db.transaction():
                        T.update("assets", aid, location=loc, assigned_to=to, condition=cond, status=stat)
                        T.insert("asset_movements", asset_id=aid, action="update",
                                 details=f"{r['location']}→{loc}; {r['condition']}→{cond}; {r['status']}→{stat}. {note}",
                                 created_by=a.uid, created_at=db.now())
                    st.rerun()
    else:
        widgets.empty("No assets registered.")
with t2, st.form("asset", clear_on_submit=True):
    x1, x2, x3 = st.columns(3)
    name, cat, tag = x1.text_input("Name"), x2.text_input("Category"), x3.text_input("Tag / serial")
    x1, x2, x3, x4 = st.columns(4)
    loc, qty = x1.text_input("Location"), x2.number_input("Quantity", 1, 100000, 1)
    val, pdate = x3.number_input("Unit value", 0.0, 1e9, 0.0), x4.date_input("Purchase date", value=None)
    if st.form_submit_button("Add item", type="primary", icon=":material/add:") and name.strip():
        aid = T.insert("assets", name=name.strip(), category=cat, tag=tag, location=loc, quantity=int(qty), value=val,
                       purchase_date=pdate.isoformat() if pdate else None, status="in_stock", condition="new")
        T.insert("asset_movements", asset_id=aid, action="added", details=f"qty {qty}", created_by=a.uid, created_at=db.now())
        st.rerun()
with t3:
    mv = T.q("""SELECT m.created_at, a.name, m.action, m.details, u.full_name AS by_user FROM asset_movements m
                JOIN assets a ON a.id=m.asset_id LEFT JOIN users u ON u.id=m.created_by WHERE m.institution_id=:iid ORDER BY m.id DESC""")
    st.dataframe(pd.DataFrame(mv), hide_index=True) if mv else widgets.empty("No movements yet.")
