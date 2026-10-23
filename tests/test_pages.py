"""Render every page for every role and institution type without exceptions."""
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ims import db

ROOT = Path(__file__).resolve().parent.parent
PAGES = sorted(p.name for p in (ROOT / "app_pages").glob("*.py") if p.name != "welcome.py")
ROLES = ["owner", "principal", "accountant", "teacher", "exam_controller", "parent", "student"]


def user_id(env, kind, role):
    if role == "owner":
        return env[kind]["uid"]
    return db.query_one("SELECT id FROM users WHERE username=?", (f"{role}{env[kind]['iid']}",))["id"]


def test_welcome_renders(env):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert any("Sign in" in s.value for s in at.subheader)


@pytest.mark.parametrize("kind", ["school", "college", "university"])
@pytest.mark.parametrize("role", ROLES)
def test_all_pages(env, kind, role):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.session_state["uid"] = user_id(env, kind, role)
    at.session_state["last_seen"] = time.time()
    at.run()
    assert not at.exception, at.exception
    failures, visited = [], 0
    for page in PAGES:
        try:
            at.switch_page(f"app_pages/{page}")
        except ValueError:
            continue  # page not in this role's navigation (permission/type/module)
        at.run()
        visited += 1
        if at.exception:
            failures.append((page, at.exception[0].message, at.exception[0].stack_trace[-3:]))
    assert not failures, failures
    if role == "owner":
        expected = len(PAGES) - 1 - (0 if kind == "university" else 1)  # no portal; registration is university-only
        assert visited == expected, (visited, expected)
