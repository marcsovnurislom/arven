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


def test_open_log_moves_an_oversized_log_aside(tmp_path):
    from arven.live.instance import open_log

    path = tmp_path / "live" / "run.log"
    with open_log(path, max_bytes=10) as fh:
        fh.write("0123456789ABC\n")
    with open_log(path, max_bytes=10) as fh:  # over the limit at open: rotated, new file starts empty
        fh.write("new\n")
    assert path.read_text(encoding="utf-8") == "new\n"
    assert (tmp_path / "live" / "run.log.1").read_text(encoding="utf-8") == "0123456789ABC\n"
    with open_log(path, max_bytes=10) as fh:  # under the limit: appended
        fh.write("more\n")
    assert path.read_text(encoding="utf-8") == "new\nmore\n"
