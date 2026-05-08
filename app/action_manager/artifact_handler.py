import logging
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)


class ArtifactHandler:
    """
    Extracts and packages artifacts produced by a sandbox execution:
    - Plots (base64-encoded PNG/SVG auto-captured from matplotlib)
    - Files generated inside the sandbox filesystem
    """

    def extract_plots(self, execution_result: dict) -> list[dict]:
        """
        Return list of plot dicts from execution result.

        Each dict: {"type": "png"|"svg", "data": "<base64 string>"}
        """
        plots = []
        for raw in execution_result.get("plots", []):
            if not raw:
                continue
            # E2B returns raw base64 strings for PNG/SVG
            plots.append({"type": "png", "data": raw})
        return plots

    def read_file(self, sandbox, remote_path: str) -> bytes | None:
        """
        Download a file from the sandbox filesystem.

        Args:
            sandbox:     Open e2b Sandbox instance
            remote_path: Absolute path inside the sandbox (e.g. "/home/user/cleaned.bed")

        Returns raw bytes, or None on failure.
        """
        try:
            content = sandbox.files.read(remote_path)
            logger.info(f"Downloaded {remote_path} from sandbox ({len(content)} bytes)")
            return content
        except Exception as exc:
            logger.warning(f"Could not read {remote_path} from sandbox: {exc}")
            return None

    def sync_uploaded_files(self, sandbox, uploaded_files: list[dict]) -> tuple[list[dict], list[str]]:
        """
        Upload local files into the sandbox filesystem.

        Returns a tuple of (synced_files, error_messages).
        """
        synced_files = []
        errors = []

        if not sandbox:
            return synced_files, ["Sandbox is not available."]

        if not uploaded_files:
            return synced_files, errors

        parent_dirs = {
            str(PurePosixPath(file_meta["sandbox_path"]).parent)
            for file_meta in uploaded_files
            if file_meta.get("sandbox_path")
        }

        for parent_dir in sorted(parent_dirs):
            try:
                sandbox.run_code(
                    (
                        "from pathlib import Path\n"
                        f"Path({parent_dir!r}).mkdir(parents=True, exist_ok=True)\n"
                    ),
                    timeout=20,
                )
            except Exception as exc:
                errors.append(f"Could not prepare sandbox directory {parent_dir}: {exc}")

        for file_meta in uploaded_files:
            local_path = file_meta.get("local_path")
            remote_path = file_meta.get("sandbox_path")

            if not local_path or not remote_path:
                errors.append("Uploaded file metadata is missing local_path or sandbox_path.")
                continue

            try:
                with open(local_path, "rb") as file_handle:
                    content = file_handle.read()
                sandbox.files.write(remote_path, content)
                synced_files.append(file_meta)
                logger.info(f"Uploaded {local_path} to sandbox path {remote_path}")
            except Exception as exc:
                errors.append(f"Could not upload {local_path} to {remote_path}: {exc}")
                logger.warning(f"Could not upload {local_path} to {remote_path}: {exc}")

        return synced_files, errors

    def list_files(self, sandbox, directory: str = "/home/user") -> list[str]:
        """List files in a sandbox directory."""
        try:
            entries = sandbox.files.list(directory) or []
            normalized = []
            for entry in entries:
                if isinstance(entry, str):
                    normalized.append(entry)
                elif isinstance(entry, dict):
                    normalized.append(entry.get("path") or entry.get("name") or str(entry))
                else:
                    normalized.append(
                        getattr(entry, "path", None)
                        or getattr(entry, "name", None)
                        or str(entry)
                    )
            return normalized
        except Exception as exc:
            logger.warning(f"Could not list {directory}: {exc}")
            return []
