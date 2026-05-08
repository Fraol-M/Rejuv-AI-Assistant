import os
import logging

from .config import describe_e2b_api_key_envs, get_e2b_api_key

logger = logging.getLogger(__name__)

TEMPLATE_ID = os.getenv("E2B_TEMPLATE_ID", "code-interpreter-v1")


class E2BExecutor:
    """
    Wraps the E2B SDK.

    Accepts an already-open sandbox from SessionManager so the same
    microVM (and its variable state) can be reused across follow-up queries.
    Falls back to creating a one-shot sandbox if none is provided.
    """

    def __init__(self):
        self.api_key = get_e2b_api_key()
        if not self.api_key:
            logger.warning(
                "E2B API key not set (%s) - sandbox execution will fail at runtime",
                describe_e2b_api_key_envs(),
            )

    def run(self, code: str, sandbox=None, timeout: int = 120) -> dict:
        """
        Execute code and return a structured result.

        Args:
            code:    Python source to execute
            sandbox: An existing open e2b Sandbox instance (from SessionManager).
                     If None, a one-shot sandbox is created and closed after execution.
            timeout: Per-execution timeout in seconds

        Returns dict with:
            stdout  — captured text output
            stderr  — error / traceback text
            exit_code — 0 on success, 1 on error
            plots   — list of base64-encoded PNG strings (auto-captured matplotlib)
            error   — full traceback string if execution raised an exception
        """
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError:
            return self._error_result(
                "e2b-code-interpreter is not installed. Install it before running E2B actions."
            )

        owned = sandbox is None
        try:
            if owned:
                logger.info("Creating one-shot E2B sandbox")
                sandbox = Sandbox.create(
                    template=TEMPLATE_ID,
                    timeout=timeout,
                    api_key=self.api_key,
                )

            logger.info(f"Executing code in sandbox (timeout={timeout}s)")
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

            exit_code = 1 if execution.error else 0
            logger.info(f"E2B execution done — exit_code={exit_code}, plots={len(plots)}")

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "plots": plots,
                "error": error_text,
            }

        except Exception as exc:
            logger.error(f"E2B sandbox error: {exc}")
            return self._error_result(str(exc))
        finally:
            if owned and sandbox is not None:
                try:
                    if hasattr(sandbox, "kill"):
                        sandbox.kill()
                    elif hasattr(sandbox, "close"):
                        sandbox.close()
                except Exception:
                    pass

    @staticmethod
    def _error_result(message: str) -> dict:
        return {
            "stdout": "",
            "stderr": message,
            "exit_code": 1,
            "plots": [],
            "error": message,
        }
