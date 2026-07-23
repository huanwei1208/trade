"""Generic retry logic and HTTP session helpers.

Example:
    @retry(delays=(1, 5, 15), on=(IOError,))
    def fetch():
        ...

    session = create_retry_session(retries=3)
    resp = session.get("https://api.example.com/data", timeout=(10, 30))
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Sequence, Type

logger = logging.getLogger(__name__)


def retry(
    delays: Sequence[float] = (1, 5, 15),
    on: tuple[Type[Exception], ...] = (Exception,),
    progress_cb: Callable[[str], None] | None = None,
):
    """Decorator: retry on specified exceptions with exponential back-off."""
    def decorator(fn: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            for attempt, delay in enumerate((*delays, None), start=1):
                try:
                    return fn(*args, **kwargs)
                except on as exc:
                    if delay is None:
                        raise
                    exc_name = type(exc).__name__
                    msg = (
                        f"[retry] {fn.__name__} attempt={attempt} "
                        f"error_type={exc_name} error={exc!r} retry_in={delay}s"
                    )
                    logger.warning(msg)
                    if progress_cb:
                        progress_cb(msg)
                    time.sleep(delay)
        return wrapper
    return decorator


# Default User-Agent used for outbound HTTP calls — some providers (Reddit,
# EastMoney, ECB mirror) throttle or block the default python-requests UA.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; TradeBot/1.0; +https://example.invalid/tradebot)"
)

# Conservative (connect, read) timeout tuple used across HTTP helpers.
DEFAULT_TIMEOUT = (10.0, 30.0)


def create_retry_session(
    retries: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
    session=None,
    user_agent: str = DEFAULT_USER_AGENT,
):
    """Build a ``requests.Session`` with a mounted ``HTTPAdapter`` that retries
    on connection-level errors and on the listed HTTP status codes.

    Retries are applied at the **urllib3** layer (before the response is
    returned to the caller), which covers transient ``RemoteDisconnected``,
    DNS failures, reset connections, and 5xx/429 responses that the
    decorator-level ``retry()`` cannot see because those failures surface
    before ``requests.get()`` returns.

    Parameters
    ----------
    retries:
        Total number of retries per request.
    backoff_factor:
        Exponential backoff multiplier applied between retries
        (sleep = backoff_factor * (2 ** (retry - 1))).
    status_forcelist:
        HTTP status codes that trigger a retry.
    session:
        Optional existing session to mount adapters onto. A new session is
        created when ``None``.
    user_agent:
        Default ``User-Agent`` header set on the session. Callers can still
        override per request via ``headers=``.
    """
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    if session is None:
        session = requests.Session()

    retry_strategy = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        redirect=3,
        backoff_factor=backoff_factor,
        status_forcelist=list(status_forcelist),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Override the default python-requests User-Agent (some providers block
    # or rate-limit the generic UA, e.g. Reddit, EastMoney mirrors). Direct
    # assignment is required because a fresh Session already has User-Agent
    # set, so setdefault() would not replace it.
    session.headers["User-Agent"] = user_agent
    session.headers.setdefault("Accept", "*/*")

    return session


# Module-level shared session with conservative defaults. Imported by HTTP
# helper modules so every provider gets connection-pooling and retries
# without constructing a fresh Session per call.
_shared_session = None


def get_default_session():
    """Return a lazily-initialized shared ``requests.Session`` with retries."""
    global _shared_session
    if _shared_session is None:
        _shared_session = create_retry_session()
    return _shared_session
