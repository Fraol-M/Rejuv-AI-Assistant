import logging

logger = logging.getLogger(__name__)

# Scientific Python packages already present in the sandbox template.
AVAILABLE_PACKAGES = [
    "pandas", "numpy", "matplotlib", "seaborn", "scikit-learn", "scipy",
]

FILES_SECTION = """Files already uploaded to the sandbox:
{files}

Use these exact sandbox paths when reading input data.
"""

CODE_GEN_PROMPT = """You are a Python coding assistant running inside a Firecracker microVM sandbox.
The sandbox already has these packages installed: {packages}.
You can also install additional packages with pip or apt-get if needed.
{files_section}

Generate a **single, self-contained Python script** that fulfils the task below.

Task:
{task}

{error_section}

Rules:
- Output ONLY raw Python code. No markdown fences, no explanation text.
- Print a clear, human-readable summary of the results to stdout.
- Prefer Python standard-library parsing for simple text formats before installing packages.
- For VCF/FASTA/FASTQ/CSV/TSV quick summaries, do lightweight parsing directly unless the user explicitly asks for a specialized package/tool.
- If generating plots (matplotlib/seaborn), call plt.show() — E2B captures them automatically.
- If the task involves files that are not present, print a clear error and exit(1).
- For subprocess calls, always capture stdout and stderr and print them.
- If the task needs an external CLI tool such as PLINK, check whether it exists first.
- If the tool is missing, install it non-interactively at runtime inside the script, then verify the executable before continuing.
- For PLINK tasks, support either `plink` or `plink2` and print which executable was used.
- Save generated outputs under /home/user unless the task explicitly says otherwise, and print the output file paths you created.
- End stdout with a compact "RESULT SUMMARY" section containing the main numbers, generated file paths, and caveats.
"""

ERROR_SECTION = """Previous attempt failed — fix the issue in your new script:
Error:
{error_context}
"""


class CodeGenerator:
    """
    Uses the LLM to generate a runnable Python script for any bioinformatics or data task.
    On retry, the previous error traceback is injected so the LLM can self-correct.
    """

    def __init__(self, llm):
        self.llm = llm

    def generate(
        self,
        task: str,
        error_context: str = None,
        available_files: list[dict] | None = None,
    ) -> str:
        error_section = (
            ERROR_SECTION.format(error_context=error_context)
            if error_context
            else ""
        )
        files_section = self._format_files_section(available_files)
        prompt = CODE_GEN_PROMPT.format(
            packages=", ".join(AVAILABLE_PACKAGES),
            files_section=files_section,
            task=task,
            error_section=error_section,
        )

        try:
            code = self.llm.generate(prompt)
            return self._strip_fences(code)
        except Exception as exc:
            logger.error(f"CodeGenerator failed: {exc}")
            return f'print("Code generation failed: {exc}")\nimport sys; sys.exit(1)'

    @staticmethod
    def _strip_fences(code: str) -> str:
        code = code.strip()
        if not code.startswith("```"):
            return code
        lines = code.splitlines()
        return "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()

    @staticmethod
    def _format_files_section(available_files: list[dict] | None) -> str:
        if not available_files:
            return "There are currently no uploaded input files in the sandbox."

        formatted_files = []
        for file_meta in available_files:
            sandbox_path = file_meta.get("sandbox_path")
            if not sandbox_path:
                continue

            filename = file_meta.get("filename")
            size_bytes = file_meta.get("size_bytes")
            details = []
            if filename:
                details.append(f"filename={filename}")
            if size_bytes is not None:
                details.append(f"size={size_bytes} bytes")

            suffix = f" ({', '.join(details)})" if details else ""
            formatted_files.append(f"- {sandbox_path}{suffix}")

        if not formatted_files:
            return "There are currently no uploaded input files in the sandbox."

        return FILES_SECTION.format(files="\n".join(formatted_files))
