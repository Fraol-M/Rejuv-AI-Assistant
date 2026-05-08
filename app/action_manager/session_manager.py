import os
import threading
import logging

from .config import get_e2b_api_key, describe_e2b_api_key_envs

logger = logging.getLogger(__name__)

TEMPLATE_ID = os.getenv("E2B_TEMPLATE_ID", "code-interpreter-v1")
SESSION_TIMEOUT = int(os.getenv("E2B_SESSION_TIMEOUT", "300"))  # seconds


class SessionManager:
    """
    Maps user_id → live E2B sandbox instance.

    Keeps sandboxes alive between follow-up queries so variables, installed
    packages, and uploaded files persist within a session.  When a session
    is explicitly closed (or on process shutdown) the microVM is destroyed.
    """

    def __init__(self):
        self._sessions: dict[str, dict[str, object]] = {}
        self._lock = threading.Lock()
        self.api_key = get_e2b_api_key()
        if not self.api_key:
            logger.warning(
                "E2B API key not set (%s) - sandbox creation will fail at runtime",
                describe_e2b_api_key_envs(),
            )

    def get_or_create(self, user_id: str):
        """Return the live sandbox for user_id, creating one if needed."""
        with self._lock:
            session = self._get_or_init_session(user_id)
            sandbox = session.get("sandbox")
            if sandbox is not None:
                try:
                    sandbox.set_timeout(SESSION_TIMEOUT)
                    logger.info(f"Reusing sandbox for user {user_id}")
                    return sandbox
                except Exception as exc:
                    logger.warning(f"Existing sandbox for {user_id} is dead ({exc}), recreating")
                    session["sandbox"] = None

            sandbox = self._create(user_id)
            if sandbox is not None:
                session["sandbox"] = sandbox
                session["version"] = int(session.get("version", 0)) + 1
            return sandbox

    def _create(self, user_id: str):
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError:
            logger.error("e2b-code-interpreter not installed")
            return None

        try:
            logger.info(f"Creating new E2B sandbox for user {user_id} (template={TEMPLATE_ID})")
            sandbox = Sandbox.create(
                template=TEMPLATE_ID,
                timeout=SESSION_TIMEOUT,
                api_key=self.api_key,
            )
            return sandbox
        except Exception as exc:
            logger.error(f"Failed to create sandbox for user {user_id}: {exc}")
            return None

    def register_uploaded_files(self, user_id: str, files: list[dict]):
        """Track uploaded local files so they can be synced into the sandbox."""
        if not files:
            return

        with self._lock:
            session = self._get_or_init_session(user_id)
            uploaded_files = session.setdefault("uploaded_files", {})
            for file_meta in files:
                sandbox_path = file_meta.get("sandbox_path")
                if not sandbox_path:
                    continue

                existing = uploaded_files.get(sandbox_path, {})
                merged = {**existing, **file_meta}
                if "synced_version" not in file_meta:
                    merged["synced_version"] = existing.get("synced_version")
                uploaded_files[sandbox_path] = merged

    def get_uploaded_files(self, user_id: str) -> list[dict]:
        """Return all locally tracked files for the user's sandbox session."""
        with self._lock:
            session = self._sessions.get(user_id, {})
            uploaded_files = session.get("uploaded_files", {})
            return list(uploaded_files.values())

    def get_synced_files(self, user_id: str) -> list[dict]:
        """Return files that are present in the current sandbox version."""
        with self._lock:
            session = self._sessions.get(user_id, {})
            uploaded_files = session.get("uploaded_files", {})
            current_version = int(session.get("version", 0))
            return [
                file_meta
                for file_meta in uploaded_files.values()
                if file_meta.get("synced_version") == current_version
            ]

    def get_unsynced_files(self, user_id: str) -> list[dict]:
        """Return files that have not been synced into the current sandbox version."""
        with self._lock:
            session = self._sessions.get(user_id, {})
            uploaded_files = session.get("uploaded_files", {})
            current_version = int(session.get("version", 0))
            return [
                file_meta
                for file_meta in uploaded_files.values()
                if file_meta.get("synced_version") != current_version
            ]

    def mark_files_synced(self, user_id: str, sandbox_paths: list[str]):
        """Mark files as synced for the current sandbox version."""
        if not sandbox_paths:
            return

        with self._lock:
            session = self._sessions.get(user_id)
            if not session:
                return

            uploaded_files = session.get("uploaded_files", {})
            current_version = int(session.get("version", 0))

            for sandbox_path in sandbox_paths:
                if sandbox_path in uploaded_files:
                    uploaded_files[sandbox_path]["synced_version"] = current_version

    def close(self, user_id: str):
        """Explicitly close and destroy the sandbox for a user."""
        with self._lock:
            session = self._sessions.pop(user_id, None)
        if session is not None and session.get("sandbox") is not None:
            try:
                sandbox = session["sandbox"]
                if hasattr(sandbox, "kill"):
                    sandbox.kill()
                elif hasattr(sandbox, "close"):
                    sandbox.close()
                logger.info(f"Closed sandbox for user {user_id}")
            except Exception as exc:
                logger.warning(f"Error closing sandbox for {user_id}: {exc}")

    def reset_sandbox(self, user_id: str):
        """Destroy only the live sandbox while keeping tracked uploaded files."""
        with self._lock:
            session = self._get_or_init_session(user_id)
            sandbox = session.get("sandbox")
            session["sandbox"] = None
            session["version"] = int(session.get("version", 0)) + 1
            for file_meta in session.get("uploaded_files", {}).values():
                file_meta["synced_version"] = None

        if sandbox is not None:
            try:
                if hasattr(sandbox, "kill"):
                    sandbox.kill()
                elif hasattr(sandbox, "close"):
                    sandbox.close()
            except Exception as exc:
                logger.warning(f"Error resetting sandbox for {user_id}: {exc}")

    def close_all(self):
        with self._lock:
            user_ids = list(self._sessions.keys())
        for uid in user_ids:
            self.close(uid)

    def _get_or_init_session(self, user_id: str) -> dict[str, object]:
        session = self._sessions.get(user_id)
        if session is None:
            session = {
                "sandbox": None,
                "version": 0,
                "uploaded_files": {},
            }
            self._sessions[user_id] = session
        return session


session_manager = SessionManager()
