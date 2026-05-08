import logging

logger = logging.getLogger(__name__)


class CriticAgent:
    """
    Validates E2B execution results generically — no tool-specific logic.

    The only question asked: did the sandbox produce usable output?
    Tool-specific parsing (e.g. PLINK QC numbers) is handled downstream
    by the LLM or by tool-specific parsers in app/action_manager/tools/.
    """

    def validate(self, result: dict) -> tuple[bool, str]:
        """
        Returns (is_valid, reason).

        is_valid=False → reason is fed back to CodeGenerator for the next attempt.
        """
        error = result.get("error", "")
        if error:
            return False, f"Execution raised an exception:\n{error[:600]}"

        if result.get("exit_code", 1) != 0:
            stderr = result.get("stderr", "")[:400]
            return False, f"Non-zero exit code. stderr:\n{stderr}"

        stdout = result.get("stdout", "").strip()
        plots = result.get("plots", [])

        if not stdout and not plots:
            return False, "No output produced — stdout is empty and no plots were generated."

        return True, "ok"
