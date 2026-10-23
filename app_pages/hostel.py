import sqlite3

import pandas as pd
import streamlit as st

from ims import db, session, ui, widgets

a = session.require("hostel.manage")
T, S = a.tenant, a.settings
ui.page_header("Hostel", "Buildings, rooms, beds, allocation, occupancy and maintenance")

rooms = T.q("""SELECT h.*, (SELECT COUNT(*) FROM hostel_allocations x WHERE x.room_id=h.id AND x.status='active') AS occupied
               FROM hostel_rooms h WHERE h.institution_id=:iid ORDER BY h.building, h.room_no""")
beds = sum(r["beds"] for r in rooms)
occ = sum(r["occupied"] for r in rooms)
m = st.container(horizontal=True)
m.metric("Rooms", len(rooms), width="stretch")
m.metric("Beds", beds, width="stretch")
m.metric("Occupancy", f"{occ / beds * 100:.0f}%" if beds else "—", f"{beds - occ} free", delta_color="off", width="stretch")

t1, t2, t3 = st.tabs(["Rooms", "Allocate", "Maintenance"])
with t1:
    if rooms:
        df = pd.DataFrame(rooms)
        st.dataframe(df[["building", "room_no", "room_type", "beds", "occupied", "fee"]], hide_index=True,
                     column_config={"occupied": st.column_config.ProgressColumn(min_value=0, max_value=max(int(df["beds"].max()), 1), format="%d")})
    with st.form("room", clear_on_submit=True):
        x1, x2, x3, x4, x5 = st.columns(5)
        b, no = x1.text_input("Building"), x2.text_input("Room no")
        nb, typ = x3.number_input("Beds", 1, 20, 2), x4.text_input("Type", "Double")
        fee = x5.number_input("Fee", 0.0, 1e7, 0.0)
        if st.form_submit_button("Add room", icon=":material/add:") and b.strip() and no.strip():
            try:
                T.insert("hostel_rooms", building=b.strip(), room_no=no.strip(), beds=int(nb), room_type=typ, fee=fee)
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("That room already exists.")
with t2:
    free = {r["id"]: f"{r['building']} {r['room_no']} ({r['beds'] - r['occupied']} free)" for r in rooms if r["occupied"] < r["beds"]}
    s = widgets.pick_student(a, "h_student", scoped=False)
    if s and free:
        rid = st.selectbox("Room", list(free), format_func=free.get)
        if st.button("Allocate", type="primary", icon=":material/bed:"):
            if T.one("hostel_allocations", "student_id=? AND status='active'", (s["id"],)):
                st.error("This student already has a room. Vacate it first.")
            else:
                room = T.get("hostel_rooms", rid)
                used = {x["bed_no"] for x in T.all("hostel_allocations", "room_id=? AND status='active'", (rid,))}
                bed = next(i for i in range(1, room["beds"] + 1) if i not in used)
                T.insert("hostel_allocations", room_id=rid, student_id=s["id"], bed_no=bed, from_date=db.today())
                session.flash(f"Allocated bed {bed}.")
                st.rerun()
    allocs = T.q("""SELECT x.id, st.first_name || ' ' || IFNULL(st.last_name,'') AS student, h.building, h.room_no, x.bed_no, x.from_date
                    FROM hostel_allocations x JOIN students st ON st.id=x.student_id JOIN hostel_rooms h ON h.id=x.room_id
                    WHERE x.institution_id=:iid AND x.status='active'""")
    if allocs:
        st.dataframe(pd.DataFrame(allocs).drop(columns="id"), hide_index=True)
        vopts = {x["id"]: f"{x['student']} · {x['building']} {x['room_no']}" for x in allocs}
        vid = st.selectbox("Vacate", list(vopts), format_func=vopts.get, index=None)
        if vid and st.button("Vacate", icon=":material/logout:"):
            T.update("hostel_allocations", vid, status="ended", to_date=db.today())
            st.rerun()
with t3:
    reqs = T.q("""SELECT m.id, h.building || ' ' || h.room_no AS room, m.description, m.status, m.created_at FROM maintenance_requests m
                  LEFT JOIN hostel_rooms h ON h.id=m.room_id WHERE m.institution_id=:iid AND m.room_id IS NOT NULL ORDER BY m.created_at DESC""")
    if reqs:
        st.dataframe(pd.DataFrame(reqs).drop(columns="id"), hide_index=True)
        open_ = {r["id"]: f"{r['room']} · {r['description'][:40]}" for r in reqs if r["status"] == "open"}
        cid = st.selectbox("Close request", list(open_), format_func=open_.get, index=None)
        if cid and st.button("Mark done"):
            T.update("maintenance_requests", cid, status="done")
            st.rerun()
    ropts = {r["id"]: f"{r['building']} {r['room_no']}" for r in rooms}
    with st.form("mr", clear_on_submit=True):
        rid = st.selectbox("Room", list(ropts), format_func=ropts.get, index=None)
        desc = st.text_input("Issue")
        if st.form_submit_button("Log request") and rid and desc.strip():
            T.insert("maintenance_requests", room_id=rid, description=desc.strip(), created_by=a.uid, created_at=db.now())
            st.rerun()
