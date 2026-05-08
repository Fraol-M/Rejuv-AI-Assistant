from pathlib import Path
import re


LOCAL_UPLOAD_ROOT = Path("uploaded_action_files")
REMOTE_UPLOAD_ROOT = Path("/home/user/uploads")
GENOTYPE_SUFFIXES = (
    ".bed",
    ".bim",
    ".fam",
    ".ped",
    ".map",
    ".raw",
    ".vcf",
    ".vcf.gz",
    ".pgen",
    ".pvar",
    ".psam",
)


def is_genotype_file(filename: str | None) -> bool:
    """Return True when the filename looks like a supported genotype input."""
    if not filename:
        return False
    lower_name = filename.lower()
    return any(lower_name.endswith(suffix) for suffix in GENOTYPE_SUFFIXES)


def secure_filename(filename: str) -> str:
    """Small filename sanitizer for uploaded action files."""
    cleaned = Path(filename).name.strip().replace("\x00", "")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", cleaned)
    return cleaned.lstrip(".")


def save_uploaded_genotype_file(file_storage, user_id: str) -> dict:
    """
    Save a genotype file locally so it can be synced into the user's sandbox.

    Returns a metadata dict that is stable across follow-up requests.
    """
    original_name = (file_storage.filename or "").strip()
    safe_name = secure_filename(Path(original_name).name)

    if not safe_name:
        raise ValueError("Uploaded genotype file must have a filename.")

    if not is_genotype_file(safe_name):
        raise ValueError(f"Unsupported genotype file type: {original_name}")

    user_dir = LOCAL_UPLOAD_ROOT / secure_filename(str(user_id))
    user_dir.mkdir(parents=True, exist_ok=True)

    local_path = user_dir / safe_name
    file_storage.save(local_path)

    return {
        "filename": safe_name,
        "local_path": str(local_path.resolve()),
        "sandbox_path": str((REMOTE_UPLOAD_ROOT / safe_name).as_posix()),
        "size_bytes": local_path.stat().st_size,
    }
