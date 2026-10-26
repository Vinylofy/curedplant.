"""Cooperative cooldown for the Linux JPC price subprocesses of one run."""
from __future__ import annotations

from contextlib import contextmanager
import os
import time


@contextmanager
def deadline_file():
    # Only the Linux price parent enables this path, inside its private tempdir.
    import fcntl
    with open(os.environ['CUREDPLANT_JPC_COOLDOWN'], 'a+', encoding='ascii') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            handle.seek(0)
            deadline = float(handle.read() or '0')
            yield handle, deadline
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def defer(seconds: float) -> None:
    if not os.environ.get('CUREDPLANT_JPC_COOLDOWN'):
        time.sleep(seconds)
        return
    with deadline_file() as (handle, deadline):
        deadline = max(deadline, time.monotonic() + seconds)
        handle.seek(0)
        handle.truncate()
        handle.write(str(deadline))
        handle.flush()
    wait()


def wait() -> None:
    if not os.environ.get('CUREDPLANT_JPC_COOLDOWN'):
        return
    while True:
        with deadline_file() as (_, deadline):
            remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        print('[JPC-DISCOVER-COOLDOWN]', {'wait_seconds': round(remaining, 1)}, flush=True)
        # Recheck afterwards: another process may have extended the pause.
        time.sleep(remaining)
