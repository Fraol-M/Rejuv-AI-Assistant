import contextvars
import os
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable


_current_tracker = contextvars.ContextVar("llm_usage_tracker", default=None)
_current_step = contextvars.ContextVar("llm_usage_step", default=None)


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def is_langsmith_enabled() -> bool:
    return bool(os.getenv("LANGSMITH_API_KEY")) and (
        _truthy_env("LANGSMITH_TRACING") or _truthy_env("LANGCHAIN_TRACING_V2")
    )


def _model_key(provider: str | None, model: str | None) -> str:
    raw = "_".join(part for part in (provider, model) if part)
    return "".join(ch if ch.isalnum() else "_" for ch in raw.upper())


def _price_from_env(provider: str | None, model: str | None) -> tuple[float | None, float | None]:
    key = _model_key(provider, model)
    input_price = os.getenv(f"LLM_COST_{key}_INPUT_PER_1M")
    output_price = os.getenv(f"LLM_COST_{key}_OUTPUT_PER_1M")
    try:
        input_price_value = float(input_price) if input_price else None
    except ValueError:
        input_price_value = None
    try:
        output_price_value = float(output_price) if output_price else None
    except ValueError:
        output_price_value = None
    return input_price_value, output_price_value


def estimate_tokens(text: Any) -> int:
    if text is None:
        return 0
    if not isinstance(text, str):
        text = str(text)
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text) // 4) if text else 0


def normalize_usage(
    usage_data: dict[str, Any] | None,
    *,
    prompt_text: str,
    completion_text: str,
) -> dict[str, Any]:
    usage_data = usage_data or {}

    prompt_tokens = (
        usage_data.get("input_tokens")
        or usage_data.get("prompt_tokens")
        or usage_data.get("input_token_count")
    )
    completion_tokens = (
        usage_data.get("output_tokens")
        or usage_data.get("completion_tokens")
        or usage_data.get("output_token_count")
    )
    total_tokens = usage_data.get("total_tokens") or usage_data.get("total_token_count")

    estimated = False
    if prompt_tokens is None:
        prompt_tokens = estimate_tokens(prompt_text)
        estimated = True
    if completion_tokens is None:
        completion_tokens = estimate_tokens(completion_text)
        estimated = True
    if total_tokens is None:
        total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)

    return {
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "estimated": estimated,
    }


def extract_usage_metadata(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        return usage

    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        token_usage = response_metadata.get("token_usage")
        if isinstance(token_usage, dict):
            return token_usage
        usage_metadata = response_metadata.get("usage_metadata")
        if isinstance(usage_metadata, dict):
            return usage_metadata

    return {}


class QueryUsageTracker:
    def __init__(self, *, user_id: str, query: str, metadata: dict[str, Any] | None = None):
        self.query_id = str(uuid.uuid4())
        self.user_id = user_id
        self.query = query
        self.metadata = metadata or {}
        self.started_at = time.time()
        self.calls: list[dict[str, Any]] = []
        self.totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": None,
        }

    def record_llm_call(
        self,
        *,
        provider: str | None,
        model: str | None,
        operation: str,
        usage: dict[str, Any],
        elapsed_ms: int,
        error: str | None = None,
    ) -> None:
        step = _current_step.get() or operation
        input_price, output_price = _price_from_env(provider, model)
        estimated_cost = None
        if input_price is not None and output_price is not None:
            estimated_cost = (
                usage["prompt_tokens"] * input_price
                + usage["completion_tokens"] * output_price
            ) / 1_000_000

        call = {
            "step": step,
            "operation": operation,
            "provider": provider,
            "model": model,
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "total_tokens": usage["total_tokens"],
            "estimated": usage["estimated"],
            "elapsed_ms": elapsed_ms,
        }
        if estimated_cost is not None:
            call["estimated_cost_usd"] = round(estimated_cost, 8)
        if error:
            call["error"] = error

        self.calls.append(call)
        self.totals["prompt_tokens"] += usage["prompt_tokens"]
        self.totals["completion_tokens"] += usage["completion_tokens"]
        self.totals["total_tokens"] += usage["total_tokens"]

        if estimated_cost is not None:
            current_cost = self.totals["estimated_cost_usd"] or 0.0
            self.totals["estimated_cost_usd"] = round(current_cost + estimated_cost, 8)

    def langsmith_config(self, *, provider: str | None, model: str | None, operation: str) -> dict[str, Any]:
        step = _current_step.get() or operation
        return {
            "run_name": f"{step}:{operation}",
            "tags": [
                "rejuv-ai-assistant",
                f"step:{step}",
                f"provider:{provider or 'unknown'}",
            ],
            "metadata": {
                "query_id": self.query_id,
                "user_id": self.user_id,
                "step": step,
                "operation": operation,
                "model_provider": provider,
                "model": model,
                **self.metadata,
            },
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "langsmith": {
                "enabled": is_langsmith_enabled(),
                "project": os.getenv("LANGSMITH_PROJECT")
                or os.getenv("LANGCHAIN_PROJECT"),
            },
            "totals": self.totals,
            "llm_calls": self.calls,
        }


@contextmanager
def start_query_tracking(
    *,
    user_id: str,
    query: str,
    metadata: dict[str, Any] | None = None,
):
    tracker = QueryUsageTracker(user_id=user_id, query=query, metadata=metadata)
    token = _current_tracker.set(tracker)
    try:
        yield tracker
    finally:
        _current_tracker.reset(token)


@contextmanager
def llm_usage_step(step_name: str):
    token = _current_step.set(step_name)
    try:
        yield
    finally:
        _current_step.reset(token)


def current_usage_tracker() -> QueryUsageTracker | None:
    return _current_tracker.get()


def tracked_node(step_name: str, fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with llm_usage_step(step_name):
            return fn(*args, **kwargs)

    return wrapper

