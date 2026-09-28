"""HTTP downloading with retries, exponential backoff, checksum verification and safe partial files.

A file is written to ``<dest>.part`` while its SHA-256 is computed, and only atomically renamed to
``<dest>`` after the digest matches the expected one. A failed or interrupted download never leaves a
file at ``<dest>``.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import random
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arven.core.config import DownloadConfig

USER_AGENT = "arven-research/0.1 (+public market data download)"
_CHUNK = 1 << 16

# Network failures worth retrying. HTTPError is handled separately (it subclasses URLError).
_TRANSIENT = (
    urllib.error.URLError,
    ConnectionError,
    TimeoutError,
    http.client.HTTPException,
    ssl.SSLError,
)


class DownloadError(Exception):
    """Download failed permanently (after retries, or a non-retryable HTTP status)."""


class NotAvailableError(DownloadError):
    """The server reports the resource does not exist (HTTP 404)."""


class ChecksumMismatchError(DownloadError):
    """Downloaded content never matched the expected SHA-256."""


class _IncompleteBody(Exception):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    timeout_seconds: float
    backoff_initial_seconds: float
    backoff_multiplier: float
    backoff_max_seconds: float

    @classmethod
    def from_config(cls, cfg: DownloadConfig) -> RetryPolicy:
        return cls(
            max_attempts=cfg.max_attempts,
            timeout_seconds=cfg.timeout_seconds,
            backoff_initial_seconds=cfg.backoff_initial_seconds,
            backoff_multiplier=cfg.backoff_multiplier,
            backoff_max_seconds=cfg.backoff_max_seconds,
        )

    def backoff(self, attempt: int, rng: random.Random) -> float:
        """Delay before retry number ``attempt`` (1-based): exponential, capped, with jitter in [50%, 100%]."""
        base = min(self.backoff_max_seconds, self.backoff_initial_seconds * self.backoff_multiplier ** (attempt - 1))
        return base * (0.5 + 0.5 * rng.random())


@dataclass(frozen=True)
class DownloadResult:
    sha256: str
    size_bytes: int
    attempts: int


Opener = Callable[..., Any]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


class Downloader:
    def __init__(
        self,
        policy: RetryPolicy,
        opener: Opener = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.policy = policy
        self._opener = opener
        self._sleep = sleep
        self._rng = rng or random.Random()

    def _open(self, url: str) -> Any:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        return self._opener(request, timeout=self.policy.timeout_seconds)

    def _with_retries(self, url: str, action: Callable[[int], Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                return action(attempt)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise NotAvailableError(f"404 Not Found: {url}") from exc
                if exc.code != 429 and exc.code < 500:
                    raise DownloadError(f"HTTP {exc.code} for {url}") from exc
                last_error = exc
                retry_after = _retry_after_seconds(exc)
            except (*_TRANSIENT, _IncompleteBody, ChecksumMismatchError) as exc:
                last_error = exc
                retry_after = None
            if attempt < self.policy.max_attempts:
                delay = self.policy.backoff(attempt, self._rng)
                self._sleep(max(delay, retry_after or 0.0))
        if isinstance(last_error, ChecksumMismatchError):
            raise last_error
        raise DownloadError(f"giving up on {url} after {self.policy.max_attempts} attempts: {last_error!r}")

    def fetch_bytes(self, url: str) -> bytes:
        """Fetch a small resource fully into memory (e.g. a CHECKSUM file)."""

        def action(_attempt: int) -> bytes:
            with self._open(url) as resp:
                body = resp.read()
                _check_length(resp, len(body))
                return body

        return self._with_retries(url, action)

    def download_file(self, url: str, dest: Path, expected_sha256: str | None) -> DownloadResult:
        """Stream ``url`` to ``dest``; verify SHA-256 before the atomic rename into place."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")

        def action(attempt: int) -> DownloadResult:
            h = hashlib.sha256()
            size = 0
            try:
                with self._open(url) as resp, part.open("wb") as fh:
                    for chunk in iter(lambda: resp.read(_CHUNK), b""):
                        fh.write(chunk)
                        h.update(chunk)
                        size += len(chunk)
                    _check_length(resp, size)
                digest = h.hexdigest()
                if expected_sha256 is not None and digest != expected_sha256:
                    raise ChecksumMismatchError(f"SHA-256 mismatch for {url}: got {digest}, expected {expected_sha256}")
                os.replace(part, dest)
                return DownloadResult(sha256=digest, size_bytes=size, attempts=attempt)
            finally:
                part.unlink(missing_ok=True)

        return self._with_retries(url, action)


def _check_length(resp: Any, received: int) -> None:
    headers = getattr(resp, "headers", None)
    declared = headers.get("Content-Length") if headers is not None else None
    if declared is not None and int(declared) != received:
        raise _IncompleteBody(f"received {received} bytes, Content-Length {declared}")


def _retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    value = exc.headers.get("Retry-After") if exc.headers else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
