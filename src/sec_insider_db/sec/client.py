from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from sec_insider_db.config import Settings

_retry_callback: ContextVar[Callable[[], None] | None] = ContextVar("sec_retry_callback", default=None)


def _is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


def _before_retry_sleep(_retry_state: object) -> None:
    callback = _retry_callback.get()
    if callback is not None:
        callback()


class SecClient:
    archives_base_url = "https://www.sec.gov/Archives"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._minimum_interval = 1.0 / settings.sec_requests_per_second
        self._last_request_at = 0.0
        self._rate_lock = threading.Lock()
        self._client = httpx.Client(
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
            headers={
                "User-Agent": settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json, text/plain, text/html, application/xml, */*",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SecClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @contextmanager
    def track_retries(self, callback: Callable[[], None]) -> Iterator[None]:
        token = _retry_callback.set(callback)
        try:
            yield
        finally:
            _retry_callback.reset(token)

    def _rate_limit(self) -> None:
        with self._rate_lock:
            now = time.monotonic()
            wait_time = self._minimum_interval - (now - self._last_request_at)
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_request_at = time.monotonic()

    @retry(
        retry=retry_if_exception(_is_retryable_exception),
        wait=wait_exponential_jitter(initial=1, max=60),
        stop=stop_after_attempt(5),
        before_sleep=_before_retry_sleep,
        reraise=True,
    )
    def get(self, url: str) -> httpx.Response:
        self._rate_limit()
        response = self._client.get(url)
        response.raise_for_status()
        return response

    def get_text(self, url: str) -> str:
        response = self.get(url)
        return response.content.decode("utf-8", errors="replace")

    def get_json(self, url: str) -> dict[str, Any]:
        response = self.get(url)
        return json.loads(response.content.decode("utf-8", errors="replace"))
