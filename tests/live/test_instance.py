"""Single-instance lock of the live process."""

from arven.live.instance import acquire


def test_second_holder_is_refused_until_the_first_releases(tmp_path):
    path = tmp_path / "live" / "live.lock"
    first = acquire(path)
    assert first is not None
    assert acquire(path) is None
    first.close()
    again = acquire(path)
    assert again is not None
    again.close()
