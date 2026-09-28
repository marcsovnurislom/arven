import hashlib
import http.client
import io
import random
import urllib.error

import pytest

from arven.data.download import (
    ChecksumMismatchError,
    DownloadError,
    Downloader,
    NotAvailableError,
    RetryPolicy,
)

POLICY = RetryPolicy(max_attempts=4, timeout_seconds=5, backoff_initial_seconds=1.0,
                     backoff_multiplier=2.0, backoff_max_seconds=3.0)
PAYLOAD = b"x" * 200_000
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, content_length: int | None = None):
        super().__init__(body)
        length = len(body) if content_length is None else content_length
        self.headers = {"Content-Length": str(length)}


def http_error(code: int, headers: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, None)


class ScriptedOpener:
    """Returns/raises the scripted outcomes in order; records call count and timeouts."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.timeouts = []

    def __call__(self, request, timeout):
        self.calls += 1
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def make(opener):
    sleeps: list[float] = []
    return Downloader(POLICY, opener=opener, sleep=sleeps.append, rng=random.Random(0)), sleeps


def test_retries_connection_reset_then_succeeds(tmp_path):
    opener = ScriptedOpener(ConnectionResetError("reset"), http.client.RemoteDisconnected("gone"), FakeResponse(PAYLOAD))
    dl, sleeps = make(opener)
    result = dl.download_file("http://x/f.zip", tmp_path / "f.zip", PAYLOAD_SHA)
    assert result.attempts == 3 and result.sha256 == PAYLOAD_SHA and result.size_bytes == len(PAYLOAD)
    assert (tmp_path / "f.zip").read_bytes() == PAYLOAD
    assert not (tmp_path / "f.zip.part").exists()
    assert len(sleeps) == 2
    assert opener.timeouts == [5, 5, 5]


def test_backoff_is_exponential_capped_and_jittered():
    rng = random.Random(1)
    for attempt, base in [(1, 1.0), (2, 2.0), (3, 3.0), (4, 3.0)]:  # capped at 3.0
        for _ in range(20):
            assert base * 0.5 <= POLICY.backoff(attempt, rng) <= base


def test_404_is_not_retried(tmp_path):
    opener = ScriptedOpener(http_error(404))
    dl, sleeps = make(opener)
    with pytest.raises(NotAvailableError):
        dl.download_file("http://x/f.zip", tmp_path / "f.zip", None)
    assert opener.calls == 1 and sleeps == []


def test_403_fails_immediately(tmp_path):
    dl, _ = make(ScriptedOpener(http_error(403)))
    with pytest.raises(DownloadError, match="HTTP 403"):
        dl.fetch_bytes("http://x/f")


def test_5xx_and_429_are_retried_honouring_retry_after(tmp_path):
    opener = ScriptedOpener(http_error(503), http_error(429, {"Retry-After": "7"}), FakeResponse(b"ok"))
    dl, sleeps = make(opener)
    assert dl.fetch_bytes("http://x/f") == b"ok"
    assert sleeps[1] == 7.0


def test_truncated_body_is_retried(tmp_path):
    opener = ScriptedOpener(FakeResponse(PAYLOAD[:1000], content_length=len(PAYLOAD)), FakeResponse(PAYLOAD))
    dl, _ = make(opener)
    assert dl.download_file("http://x/f.zip", tmp_path / "f.zip", PAYLOAD_SHA).attempts == 2


def test_persistent_checksum_mismatch_leaves_no_file(tmp_path):
    opener = ScriptedOpener(*[FakeResponse(b"corrupted") for _ in range(POLICY.max_attempts)])
    dl, _ = make(opener)
    with pytest.raises(ChecksumMismatchError):
        dl.download_file("http://x/f.zip", tmp_path / "f.zip", PAYLOAD_SHA)
    assert opener.calls == POLICY.max_attempts
    assert list(tmp_path.iterdir()) == []


def test_existing_file_not_clobbered_by_failed_download(tmp_path):
    dest = tmp_path / "f.zip"
    dest.write_bytes(b"previous good content")
    dl, _ = make(ScriptedOpener(*[ConnectionResetError() for _ in range(POLICY.max_attempts)]))
    with pytest.raises(DownloadError, match="giving up"):
        dl.download_file("http://x/f.zip", dest, PAYLOAD_SHA)
    assert dest.read_bytes() == b"previous good content"
    assert not (tmp_path / "f.zip.part").exists()
