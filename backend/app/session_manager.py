import os
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
from config import SESSION_TIMEOUT_MINUTES


class SessionManager:
    def __init__(self, timeout_minutes: int = SESSION_TIMEOUT_MINUTES):
        self.timeout_seconds = timeout_minutes * 60
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def create_session(self, session_id: str) -> str:
        with self._lock:
            temp_dir = tempfile.mkdtemp(prefix=f"session_{session_id}_")
            self._sessions[session_id] = {
                "temp_dir": temp_dir,
                "created_at": datetime.now(timezone.utc),
                "last_activity": datetime.now(timezone.utc),
            }
            return temp_dir

    def touch(self, session_id: str):
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id]["last_activity"] = datetime.now(timezone.utc)

    def get_session(self, session_id: str) -> dict | None:
        with self._lock:
            return self._sessions.get(session_id)

    def destroy_session(self, session_id: str):
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session and os.path.exists(session["temp_dir"]):
                shutil.rmtree(session["temp_dir"], ignore_errors=True)

    def _cleanup_loop(self):
        while True:
            time.sleep(60)
            now = datetime.now(timezone.utc)
            expired = []
            with self._lock:
                for sid, info in self._sessions.items():
                    elapsed = (now - info["last_activity"]).total_seconds()
                    if elapsed > self.timeout_seconds:
                        expired.append(sid)

            for sid in expired:
                self.destroy_session(sid)
                print(f"Session {sid} expired and cleaned up after {self.timeout_seconds // 60}min inactivity")

    def active_sessions(self) -> list[dict]:
        with self._lock:
            result = []
            now = datetime.now(timezone.utc)
            for sid, info in self._sessions.items():
                result.append({
                    "session_id": sid,
                    "created_at": info["created_at"].isoformat(),
                    "last_activity": info["last_activity"].isoformat(),
                    "idle_seconds": int((now - info["last_activity"]).total_seconds()),
                })
            return result
