"""Bounded, cached API availability observations; no persistent permission writes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
import time


class AvailabilityMonitor:
    def __init__(self, *, clock=time.monotonic, refresh_seconds=10, stale_seconds=45,
                 max_workers=4, max_pending=64):
        self.clock, self.refresh_seconds, self.stale_seconds = clock, refresh_seconds, stale_seconds
        self.max_pending = max_pending
        self._lock = threading.RLock()
        self._entries, self._futures = {}, set()
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ezllmrouter-availability")

    @staticmethod
    def _unknown(configuration, reason="NOT_CHECKED"):
        return {"state": "unknown", "reason": reason, "checked_at": None, "latency_ms": None,
                "reachable": None, "stale": False, "configuration": configuration}

    def get(self, identifier, configuration):
        with self._lock:
            entry = self._entries.get(identifier)
            if not entry or entry["configuration"] != configuration:
                return self._unknown(configuration)
            result = dict(entry.get("result") or self._unknown(configuration))
            result["configuration"] = configuration
            result["stale"] = bool(entry.get("finished") is not None and
                                    self.clock() - entry["finished"] > self.stale_seconds)
            if entry.get("future") is not None and not entry["future"].done():
                result.update(state="checking", reason="CHECK_IN_PROGRESS")
            return result

    def request(self, identifier, configuration, check, *, force=False):
        with self._lock:
            if self._closed:
                return self._unknown(configuration, "CHECK_STOPPED")
            now = self.clock()
            entry = self._entries.get(identifier)
            if entry and entry["configuration"] == configuration:
                if entry.get("future") is not None and not entry["future"].done():
                    return self.get(identifier, configuration)
                cooldown = 2 if force else self.refresh_seconds
                if now - entry["requested"] < cooldown:
                    return self.get(identifier, configuration)
            if len(self._futures) >= self.max_pending:
                return self._unknown(configuration, "CHECK_QUEUE_FULL")
            if identifier not in self._entries and len(self._entries) >= 512:
                removable = [key for key, item in self._entries.items()
                             if item.get("future") is None or item["future"].done()]
                if removable:
                    oldest = min(removable, key=lambda key: self._entries[key]["requested"])
                    self._entries.pop(oldest, None)
            if not entry or entry["configuration"] != configuration:
                entry = {"configuration": configuration}
                self._entries[identifier] = entry
            entry["requested"] = now
            future = self._executor.submit(self._run, identifier, entry, check)
            entry["future"] = future
            self._futures.add(future)
            future.add_done_callback(self._finished)
            return self.get(identifier, configuration)

    def _run(self, identifier, entry, check):
        started = time.monotonic()
        try:
            observation = check()
            if observation.get("state") not in ("online", "offline", "attention", "blocked", "unknown"):
                raise ValueError("invalid availability observation")
            result = {key: observation[key] for key in ("state", "reason", "reachable", "model_count")
                      if key in observation}
        except Exception:
            result = {"state": "attention", "reason": "CHECK_FAILED", "reachable": None}
        result.update(checked_at=datetime.now(timezone.utc).isoformat(),
                      latency_ms=max(0, round((time.monotonic() - started) * 1000)))
        with self._lock:
            if not self._closed and self._entries.get(identifier) is entry:
                entry.update(result=result, finished=self.clock())

    def _finished(self, future):
        with self._lock:
            self._futures.discard(future)

    def close(self):
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)
