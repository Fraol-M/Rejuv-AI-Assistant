import base64
import logging
import os
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from .config import describe_e2b_api_key_envs, get_e2b_api_key

logger = logging.getLogger(__name__)


E2B_TEMPLATE_ID = os.getenv("E2B_TEMPLATE_ID", "code-interpreter-v1")


@dataclass
class SandboxResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 1
    plots: list[Any] = field(default_factory=list)
    error: str = ""
    files: list[str] = field(default_factory=list)
    backend: str = "unknown"
    backend_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "plots": self.plots,
            "error": self.error,
            "files": self.files,
            "backend": self.backend,
            "backend_error": self.backend_error,
        }


class E2BBackend:
    name = "e2b"

    def __init__(self):
        self.api_key = get_e2b_api_key()
        if not self.api_key:
            logger.warning(
                "E2B API key not set (%s) - sandbox execution will fail at runtime",
                describe_e2b_api_key_envs(),
            )

    def run(self, code: str, sandbox=None, timeout: int = 120) -> dict[str, Any]:
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError:
            return SandboxResult(
                stderr="e2b-code-interpreter is not installed.",
                error="e2b-code-interpreter is not installed.",
                backend=self.name,
                backend_error=True,
            ).to_dict()

        owned = sandbox is None
        try:
            if owned:
                logger.info("Creating one-shot E2B sandbox")
                sandbox = Sandbox.create(
                    template=E2B_TEMPLATE_ID,
                    timeout=timeout,
                    api_key=self.api_key,
                )

            logger.info("Executing code in E2B sandbox (timeout=%ss)", timeout)
            execution = sandbox.run_code(code, timeout=timeout)

            stdout = "\n".join(execution.logs.stdout) if execution.logs else ""
            stderr = "\n".join(execution.logs.stderr) if execution.logs else ""
            error_text = str(execution.error) if execution.error else ""

            plots = []
            for result in (execution.results or []):
                if hasattr(result, "png") and result.png:
                    plots.append(result.png)
                elif hasattr(result, "svg") and result.svg:
                    plots.append(result.svg)

            return SandboxResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=1 if execution.error else 0,
                plots=plots,
                error=error_text,
                backend=self.name,
            ).to_dict()

        except Exception as exc:
            error = str(exc)
            logger.error("E2B sandbox error: %s", error)
            return SandboxResult(
                stderr=error,
                error=error,
                backend=self.name,
                backend_error=self._is_backend_error(error),
            ).to_dict()
        finally:
            if owned and sandbox is not None:
                self.close(sandbox)

    @staticmethod
    def close(sandbox):
        try:
            if hasattr(sandbox, "kill"):
                sandbox.kill()
            elif hasattr(sandbox, "close"):
                sandbox.close()
        except Exception:
            pass

    @staticmethod
    def _is_backend_error(error: str) -> bool:
        lowered = error.lower()
        return any(
            marker in lowered
            for marker in (
                "api key",
                "unauthorized",
                "timeout",
                "port is not open",
                "bad gateway",
                "connection",
                "sandbox is running",
                "template",
            )
        )


class DockerBackend:
    name = "docker"

    def __init__(self):
        self.image = os.getenv("ACTION_SANDBOX_DOCKER_IMAGE", "rejuv-action-sandbox:latest")
        self.timeout = int(os.getenv("ACTION_SANDBOX_DOCKER_TIMEOUT", "120"))
        self.memory = os.getenv("ACTION_SANDBOX_DOCKER_MEMORY", "1g")
        self.cpus = float(os.getenv("ACTION_SANDBOX_DOCKER_CPUS", "1"))
        self.pids_limit = int(os.getenv("ACTION_SANDBOX_DOCKER_PIDS_LIMIT", "256"))
        self.user = os.getenv("ACTION_SANDBOX_DOCKER_USER", "sandbox")
        self.workdir = os.getenv("ACTION_SANDBOX_DOCKER_WORKDIR", "/home/user")
        self.tmp_size = os.getenv("ACTION_SANDBOX_DOCKER_TMP_SIZE", "100m")
        self.workdir_size = os.getenv("ACTION_SANDBOX_DOCKER_WORKDIR_SIZE", "512m")
        self.allow_internet = os.getenv(
            "ACTION_SANDBOX_ALLOW_DOCKER_INTERNET", "false"
        ).lower() == "true"
        self.network = os.getenv(
            "ACTION_SANDBOX_DOCKER_NETWORK",
            "bridge" if self.allow_internet else "none",
        )

    def run(
        self,
        code: str,
        uploaded_files: list[dict] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        try:
            import docker
            from docker.errors import ImageNotFound
        except ImportError:
            return SandboxResult(
                stderr="Docker SDK for Python is not installed.",
                error="Docker SDK for Python is not installed.",
                backend=self.name,
                backend_error=True,
            ).to_dict()

        timeout = timeout or self.timeout
        container = None
        try:
            client = docker.from_env()
            try:
                client.images.get(self.image)
            except ImageNotFound:
                logger.info("Pulling Docker sandbox image %s", self.image)
                try:
                    client.images.pull(self.image)
                except Exception as exc:
                    return SandboxResult(
                        stderr=f"Docker sandbox image {self.image!r} is not available: {exc}",
                        error=f"Docker sandbox image {self.image!r} is not available: {exc}",
                        backend=self.name,
                        backend_error=True,
                    ).to_dict()

            container = client.containers.create(
                image=self.image,
                command=["sleep", str(max(timeout + 30, 60))],
                detach=True,
                working_dir=self.workdir,
                network_mode=self.network,
                mem_limit=self.memory,
                nano_cpus=int(self.cpus * 1_000_000_000),
                pids_limit=self.pids_limit,
                read_only=True,
                tmpfs={
                    "/tmp": f"rw,nosuid,nodev,size={self.tmp_size},uid=1000,gid=1000",
                    self.workdir: f"rw,nosuid,nodev,size={self.workdir_size},uid=1000,gid=1000",
                },
                user=self.user,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
            )
            container.start()
            self._upload_files(container, code, uploaded_files or [])

            exec_result = container.exec_run(
                ["sh", "-lc", f"timeout {int(timeout)} python {self.workdir}/task.py"],
                demux=True,
            )
            stdout_raw, stderr_raw = exec_result.output or (b"", b"")
            stdout = self._decode(stdout_raw)
            stderr = self._decode(stderr_raw)
            files = self._list_files(container)
            exit_code = int(exec_result.exit_code or 0)
            error = stderr if exit_code != 0 else ""
            if exit_code == 124:
                error = f"Docker sandbox timed out after {timeout}s."
                stderr = (stderr + "\n" + error).strip()

            return SandboxResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                error=error,
                files=files,
                backend=self.name,
            ).to_dict()

        except Exception as exc:
            error = str(exc)
            logger.error("Docker sandbox error: %s", error)
            return SandboxResult(
                stderr=error,
                error=error,
                backend=self.name,
                backend_error=True,
            ).to_dict()
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    def _upload_files(self, container, code: str, uploaded_files: list[dict]):
        self._write_bytes(container, f"{self.workdir}/task.py", code.encode("utf-8"))
        for file_meta in uploaded_files:
            local_path = file_meta.get("local_path")
            sandbox_path = file_meta.get("sandbox_path")
            if not local_path or not sandbox_path:
                continue
            remote_path = PurePosixPath(sandbox_path)
            if not self._is_under_workdir(remote_path):
                remote_path = PurePosixPath(self.workdir) / "uploads" / remote_path.name
            with open(local_path, "rb") as file_handle:
                self._write_bytes(container, str(remote_path), file_handle.read())

    def _is_under_workdir(self, remote_path: PurePosixPath) -> bool:
        try:
            remote_path.relative_to(PurePosixPath(self.workdir))
            return True
        except ValueError:
            return False

    @staticmethod
    def _write_bytes(container, remote_path: str, content: bytes):
        init_code = (
            "from pathlib import Path\n"
            f"path = Path({remote_path!r})\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            "path.write_bytes(b'')\n"
        )
        init_result = container.exec_run(["python", "-c", init_code], demux=True)
        if init_result.exit_code != 0:
            raise RuntimeError(f"Could not prepare {remote_path}: {init_result.output}")

        chunk_size = 24_000
        for index in range(0, len(content), chunk_size):
            encoded = base64.b64encode(content[index : index + chunk_size]).decode("ascii")
            append_code = (
                "import base64\n"
                "from pathlib import Path\n"
                f"path = Path({remote_path!r})\n"
                f"chunk = base64.b64decode({encoded!r})\n"
                "with path.open('ab') as handle:\n"
                "    handle.write(chunk)\n"
            )
            result = container.exec_run(["python", "-c", append_code], demux=True)
            if result.exit_code != 0:
                raise RuntimeError(f"Could not write {remote_path}: {result.output}")

    @staticmethod
    def _decode(value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return value.decode("utf-8", errors="replace")

    @staticmethod
    def _list_files(container) -> list[str]:
        result = container.exec_run(
            [
                "python",
                "-c",
                (
                    "from pathlib import Path\n"
                    "for p in Path('/home/user').rglob('*'):\n"
                    "    if p.is_file(): print(str(p))\n"
                ),
            ],
            demux=True,
        )
        stdout_raw, _ = result.output or (b"", b"")
        return [
            line.strip()
            for line in DockerBackend._decode(stdout_raw).splitlines()
            if line.strip()
        ]


class ActionSandboxRunner:
    def __init__(self):
        self.primary = os.getenv("ACTION_SANDBOX_BACKEND", "e2b").lower()
        self.fallback = os.getenv("ACTION_SANDBOX_FALLBACK", "docker").lower()
        self.e2b_backend = E2BBackend()
        self.docker_backend = DockerBackend()

    def run(
        self,
        code: str,
        *,
        e2b_sandbox=None,
        uploaded_files: list[dict] | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        primary_result = self._run_backend(
            self.primary,
            code,
            e2b_sandbox=e2b_sandbox,
            uploaded_files=uploaded_files,
            timeout=timeout,
        )
        if not self._should_fallback(primary_result):
            return primary_result

        if not self.fallback or self.fallback == self.primary:
            return primary_result

        logger.warning(
            "Action sandbox backend %s failed due to backend error; falling back to %s",
            primary_result.get("backend"),
            self.fallback,
        )
        fallback_result = self._run_backend(
            self.fallback,
            code,
            e2b_sandbox=e2b_sandbox,
            uploaded_files=uploaded_files,
            timeout=timeout,
        )
        fallback_result["fallback_from"] = primary_result.get("backend")
        fallback_result["primary_error"] = primary_result.get("error")
        return fallback_result

    def _run_backend(
        self,
        backend_name: str,
        code: str,
        *,
        e2b_sandbox=None,
        uploaded_files: list[dict] | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        if backend_name == "docker":
            return self.docker_backend.run(
                code,
                uploaded_files=uploaded_files,
                timeout=timeout,
            )
        return self.e2b_backend.run(code, sandbox=e2b_sandbox, timeout=timeout)

    @staticmethod
    def _should_fallback(result: dict[str, Any]) -> bool:
        if result.get("backend_error"):
            return True
        error = str(result.get("error") or result.get("stderr") or "").lower()
        return any(
            marker in error
            for marker in (
                "port is not open",
                "bad gateway",
                "connection",
                "api key",
                "unauthorized",
                "template",
                "docker sdk",
            )
        )
