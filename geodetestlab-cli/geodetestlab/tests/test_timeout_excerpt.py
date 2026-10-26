"""A timed-out command reports what it printed before the timeout."""

import subprocess


def test_timeout_excerpt_includes_partial_output() -> None:
    from lib.executor import timeout_output_excerpt

    exc = subprocess.TimeoutExpired(["geode"], 30, output=b"Creating full backup\n", stderr="Progress: 40%\n")
    text = timeout_output_excerpt(exc)
    assert "Creating full backup" in text
    assert "Progress: 40%" in text
    assert timeout_output_excerpt(subprocess.TimeoutExpired(["x"], 1)) == ""
