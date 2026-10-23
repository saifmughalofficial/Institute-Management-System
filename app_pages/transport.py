import pandas as pd
import streamlit as st

from ims import db, session, ui, widgets

a = session.require("transport.manage")
T, S = a.tenant, a.settings
ui.page_header("Transport", "Routes, stops, vehicles, drivers and assigned students")

t1, t2, t3 = st.tabs(["Routes & vehicles", "Assign students", "Assigned students"])
with t1:
    rows = T.q("""SELECT r.id, r.name, r.stops, r.fee, (SELECT COUNT(*) FROM transport_assignments x WHERE x.route_id=r.id
                  AND x.status='active') AS students FROM transport_routes r WHERE r.institution_id=:iid ORDER BY r.name""")
    st.dataframe(pd.DataFrame(rows).drop(columns="id"), hide_index=True) if rows else widgets.empty("No routes yet.")
    with st.form("route", clear_on_submit=True):
        x1, x2, x3 = st.columns([2, 3, 1])
        name, stops = x1.text_input("Route name"), x2.text_input("Stops (comma separated)")
        fee = x3.number_input("Fee", 0.0, 1e7, 0.0)
        if st.form_submit_button("Add route", icon=":material/add:") and name.strip():
            T.insert("transport_routes", name=name.strip(), stops=stops, fee=fee)
            st.rerun()
    veh = T.q("""SELECT v.reg_no, v.capacity, v.driver_name, v.driver_phone, r.name AS route FROM transport_vehicles v
                 LEFT JOIN transport_routes r ON r.id=v.route_id WHERE v.institution_id=:iid""")
    if veh:
        st.dataframe(pd.DataFrame(veh), hide_index=True)
    ropts = {r["id"]: r["name"] for r in rows}
    with st.form("veh", clear_on_submit=True):
        x1, x2, x3, x4, x5 = st.columns(5)
        reg, cap = x1.text_input("Registration no"), x2.number_input("Capacity", 1, 120, 30)
        drv, ph = x3.text_input("Driver"), x4.text_input("Driver phone")
        rid = x5.selectbox("Route", list(ropts), format_func=ropts.get, index=None)
        if st.form_submit_button("Add vehicle", icon=":material/directions_bus:") and reg.strip():
            T.insert("transport_vehicles", reg_no=reg.strip(), capacity=int(cap), driver_name=drv, driver_phone=ph, route_id=rid)
            st.rerun()
with t2:
    ropts = {r["id"]: r["name"] for r in T.all("transport_routes", order="name")}
    s = widgets.pick_student(a, "tr_student", scoped=False)
    if s and ropts:
        rid = st.selectbox("Route", list(ropts), format_func=ropts.get)
        stop = st.text_input("Stop")
        if st.button("Assign", type="primary", icon=":material/link:"):
            with db.transaction():
                db.execute("UPDATE transport_assignments SET status='ended' WHERE student_id=? AND institution_id=?", (s["id"], a.iid))
                T.insert("transport_assignments", student_id=s["id"], route_id=rid, stop_name=stop, from_date=db.today())
            session.flash("Student assigned to route.")
            st.rerun()
with t3:
    rows = T.q("""SELECT st.admission_no, st.first_name || ' ' || IFNULL(st.last_name,'') AS student, r.name AS route, x.stop_name, x.from_date
                  FROM transport_assignments x JOIN students st ON st.id=x.student_id JOIN transport_routes r ON r.id=x.route_id
                  WHERE x.institution_id=:iid AND x.status='active' ORDER BY r.name""")
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True) if rows else widgets.empty("No assignments.")
    widgets.export_buttons(a, "Transport assignments", df, "tr_exp", perm=None)
