"""Streamlit session helpers: sign-in state, idle timeout, page guards."""
from __future__ import annotations

import secrets
import time

import streamlit as st

from .accounts import ValidationError
from .actor import Actor, PermissionDenied
from .db import TenantError

IDLE_MINUTES = 60
FRIENDLY_ERRORS = (ValidationError, PermissionDenied, TenantError, ValueError)


def session_key() -> str:
    if "_sk" not in st.session_state:
        st.session_state["_sk"] = secrets.token_hex(12)
    return st.session_state["_sk"]


def sign_in(user: dict):
    keep = st.session_state.get("_sk")
    st.session_state.clear()
    st.session_state["_sk"] = keep or secrets.token_hex(12)
    st.session_state["uid"] = user["id"]
    st.session_state["last_seen"] = time.time()


def sign_out(message: str | None = None):
    keep = st.session_state.get("_sk")
    st.session_state.clear()
    if keep:
        st.session_state["_sk"] = keep
    if message:
        flash(message, "info")


def current_actor() -> Actor | None:
    uid = st.session_state.get("uid")
    if not uid:
        return None
    if time.time() - st.session_state.get("last_seen", 0) > IDLE_MINUTES * 60:
        sign_out("You were signed out after 60 minutes of inactivity.")
        return None
    st.session_state["last_seen"] = time.time()
    actor = Actor.load(uid)
    if actor is None:
        sign_out("Your account is no longer active.")
    return actor


def actor() -> Actor:
    a = st.session_state.get("_actor")
    if a is None:
        st.stop()
    return a


def require(*perms: str) -> Actor:
    a = actor()
    if perms and not a.can(*perms):
        st.error("You do not have permission to open this page.", icon=":material/lock:")
        st.stop()
    return a


def flash(message: str, kind: str = "success"):
    st.session_state.setdefault("_flash", []).append((kind, message))


def show_flashes():
    icons = {"success": ":material/check_circle:", "info": ":material/info:", "warning": ":material/warning:"}
    for kind, msg in st.session_state.pop("_flash", []):
        st.toast(msg, icon=icons.get(kind, ":material/info:"))


def attempt(fn, *args, success: str | None = None, rerun: bool = False, **kwargs):
    """Run a service call; show friendly errors instead of tracebacks."""
    try:
        result = fn(*args, **kwargs)
    except FRIENDLY_ERRORS as exc:
        st.error(str(exc), icon=":material/error:")
        return None
    if success:
        flash(success)
    if rerun:
        st.rerun()
    if success:
        show_flashes()
    return result if result is not None else True
