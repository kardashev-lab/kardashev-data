from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")

_RETRYABLE_EXCEPTIONS = (
    OSError,          # network-level: connection reset, timeout, DNS
    TimeoutError,
)

try:
    import requests
    _RETRYABLE_EXCEPTIONS = (*_RETRYABLE_EXCEPTIONS, requests.exceptions.RequestException)
except ImportError:
    pass


def with_retry(
    fn: Callable[..., T],
    *args,
    attempts: int = 3,
    base_delay: float = 2.0,
    **kwargs,
) -> T:
    """Call fn(*args, **kwargs), retrying on transient errors with exponential backoff.

    Retries on network/IO errors only. Non-retryable exceptions (ValueError,
    KeyError, etc.) propagate immediately on the first attempt.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            log.warning(
                "%s transient error (attempt %d/%d): %s — retrying in %.0fs",
                getattr(fn, "__name__", repr(fn)),
                attempt,
                attempts,
                exc,
                delay,
            )
            time.sleep(delay)
        except Exception:
            raise
    raise last_exc  # type: ignore[misc]
