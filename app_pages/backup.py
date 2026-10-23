from datetime import datetime

import streamlit as st

from ims import backup, exports, session, ui

a = session.require("backup.manage")
T = a.tenant
ui.page_header("Backup & restore", "One ZIP holds this institution's database records and uploaded files")

c1, c2 = st.columns(2, gap="large")
with c1, st.container(border=True):
    st.markdown("**Download a backup**")
    st.write("Includes every record and uploaded file of **this institution only**. Keep copies in a separate, "
             "access-controlled location (a backup on the same disk is not enough).")

    def build():
        a.log("backup_downloaded", "institution", a.iid)
        return backup.create_backup(a.iid)

    st.download_button("Download backup (.zip)", build,
                       f"{exports.safe_filename(a.inst['name'])}_backup_{datetime.now():%Y%m%d_%H%M}.zip",
                       "application/zip", type="primary", icon=":material/cloud_download:", on_click="ignore")
    counts = {t: T.count(t) for t in ("students", "staff", "invoices", "payments", "results", "attendance", "documents")}
    st.caption(" · ".join(f"{k}: {v}" for k, v in counts.items()))
with c2, st.container(border=True):
    st.markdown("**Restore from a backup**")
    st.warning("Restoring replaces all current data of this institution with the backup's contents.", icon=":material/warning:")
    up = st.file_uploader("Backup file", type=["zip"], max_upload_size=200)
    confirm = st.text_input(f"Type the institution name to confirm: {a.inst['name']}")
    if st.button("Restore now", disabled=up is None or confirm.strip() != a.inst["name"], icon=":material/restore:"):
        if session.attempt(backup.restore, up.getvalue(), expected_iid=a.iid):
            session.flash("Backup restored. Please sign in again.")
            session.sign_out("Backup restored. Please sign in again.")
            st.rerun()

st.info("**Hosting note:** Streamlit Community Cloud storage is temporary. The database resets when the app restarts. "
        "Download backups regularly; after a restart use **Restore from backup** on the sign-in page. For permanent "
        "multi-user production use PostgreSQL and private file storage.", icon=":material/info:")
