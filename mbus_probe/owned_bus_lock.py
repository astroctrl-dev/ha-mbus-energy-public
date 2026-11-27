"""Non-reentrant shared bus lock with explicit thread ownership."""
import threading


class OwnedBusLock:
    def __init__(self):
        self._lock = threading.Lock()
        self._owner = None
        self._lease = None

    def acquire(self, blocking=True, timeout=-1):
        if self.owned_by_current_thread():
            raise RuntimeError("recursive bus acquisition")
        acquired = self._lock.acquire(blocking, timeout)
        if acquired:
            self._owner = threading.current_thread()
            self._lease = object()
        return acquired

    def release(self):
        if not self.owned_by_current_thread():
            raise RuntimeError("bus lock not owned by current thread")
        self._lease = None
        self._owner = None
        self._lock.release()

    def locked(self):
        return self._lock.locked()

    def owned_by_current_thread(self):
        return self._owner is threading.current_thread()

    def current_lease(self):
        return self._lease if self.owned_by_current_thread() else None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()
