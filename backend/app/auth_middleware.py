import httpx
import streamlit as st
from config import JWT_SECRET_KEY, JWT_ALGORITHM
from jose import JWTError, jwt

AUTH_API_BASE = "http://localhost:8000"


def _decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return {"username": payload.get("sub"), "role": payload.get("role")}
    except JWTError:
        return None


def login_page():
    st.markdown("### Login")
    username = st.text_input("Username", key="login_username")
    password = st.text_input("Password", type="password", key="login_password")

    if st.button("Login", key="login_button"):
        try:
            r = httpx.post(
                f"{AUTH_API_BASE}/auth/login",
                data={"username": username, "password": password},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                st.session_state["auth_token"] = data["access_token"]
                st.session_state["username"] = data["username"]
                st.session_state["role"] = data["role"]
                st.success(f"Welcome, {data['username']}! (Role: {data['role']})")
                st.rerun()
            else:
                st.error("Invalid username or password")
        except httpx.ConnectError:
            st.error("Auth server not reachable. Start it with: uvicorn auth:app --port 8000")


def require_auth(allowed_roles: list[str] | None = None) -> bool:
    if "auth_token" not in st.session_state:
        login_page()
        return False

    user = _decode_token(st.session_state["auth_token"])
    if user is None:
        st.warning("Session expired. Please log in again.")
        for key in ["auth_token", "username", "role"]:
            st.session_state.pop(key, None)
        login_page()
        return False

    if allowed_roles and user["role"] not in allowed_roles:
        st.error(f"Access denied. Your role '{user['role']}' cannot access this page.")
        return False

    return True


def get_current_user() -> dict | None:
    token = st.session_state.get("auth_token")
    if not token:
        return None
    return _decode_token(token)


def is_admin() -> bool:
    user = get_current_user()
    return user is not None and user.get("role") == "admin"


def logout():
    for key in ["auth_token", "username", "role"]:
        st.session_state.pop(key, None)
