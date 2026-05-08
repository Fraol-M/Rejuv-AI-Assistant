import os


E2B_API_KEY_ENV_NAMES = ("E2B_API_KEY", "E2B_Sandbox_KEY")


def get_e2b_api_key() -> str | None:
    """Return the first configured E2B API key from the supported env vars."""
    for env_name in E2B_API_KEY_ENV_NAMES:
        value = os.getenv(env_name)
        if value:
            return value
    return None


def describe_e2b_api_key_envs() -> str:
    """Human-readable list of accepted E2B API key env vars."""
    return " or ".join(E2B_API_KEY_ENV_NAMES)
