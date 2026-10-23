import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["IMS_PBKDF2_ITERATIONS"] = "1000"


@pytest.fixture(scope="session")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ims")
    os.environ["IMS_DB_PATH"] = str(tmp / "test.sqlite3")
    os.environ["IMS_MEDIA_ROOT"] = str(tmp / "media")
    from ims import db
    db.configure(tmp / "test.sqlite3", tmp / "media")
    db.init_db()
    from ims import accounts, demo
    out = {}
    for i, kind in enumerate(["school", "college", "university"]):
        iid, uid = accounts.create_workspace(institution_type=kind, name=f"Test {kind.title()} {i}", logo_png=None,
                                             admin_name="Owner", username=f"owner{i}", email=f"o{i}@t.com",
                                             password="Secret123", session_key=f"k{i}")
        out[kind] = {"iid": iid, "uid": uid, "logins": demo.seed(uid)}
    return out
