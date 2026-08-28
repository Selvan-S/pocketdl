import asyncio


class ChangeNotifier:
    """Wakes anything waiting on "the server's state changed".

    The PWA used to poll four endpoints every two seconds whether or not
    anything had happened, which cost a request storm on a phone and made the
    UI re-render lists that had not changed. Subscribers now sleep until this
    is fired.

    **Level-triggered, not edge-triggered.** A subscriber spends most of its
    cycle *not* waiting -- it is building and writing its snapshot, and
    throttling between pushes -- and a plain broadcast fired during that
    window would be lost, stranding the client until the next heartbeat. So
    each notification bumps a version, and a subscriber waits on "has the
    version moved past the one I last built for". Reading `version` before
    building a snapshot and passing it to `wait()` therefore cannot miss a
    change, however the two interleave.

    Deliberately carries no payload and names no topic: a subscriber rebuilds
    whatever it serves and decides for itself whether the result is worth
    sending, so a spurious notification degrades to a redundant check rather
    than to wrong data on someone's screen. That is also why subscribers keep
    their own heartbeat timeout -- correctness must not depend on this being
    fired from every mutation site.
    """

    def __init__(self) -> None:
        self._version = 0
        self._waiters: set[asyncio.Event] = set()

    @property
    def version(self) -> int:
        """Read this *before* building a snapshot, then pass it to `wait()`."""
        return self._version

    def notify(self) -> None:
        """Record a change and wake every waiter. Safe to call from anywhere
        on the loop, and cheap enough for every download progress tick --
        subscribers do their own coalescing."""
        self._version += 1
        for waiter in self._waiters:
            waiter.set()

    async def wait(self, *, since: int, timeout: float) -> bool:
        """Block until the version moves past `since`, or `timeout` elapses.

        Returns True if there is a change to pick up, False on timeout (i.e.
        a heartbeat). Returns immediately when the version already moved
        while the caller was busy.
        """
        if self._version != since:
            return True

        waiter = asyncio.Event()
        self._waiters.add(waiter)
        try:
            await asyncio.wait_for(waiter.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self._waiters.discard(waiter)

    @property
    def subscriber_count(self) -> int:
        return len(self._waiters)
