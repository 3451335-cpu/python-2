"""Run queued jobs in one background thread."""

import subprocess
import sys
from pathlib import Path
from queue import Queue
from threading import Event, Thread

PENDING = 0
WORKER_TIMEOUT = 10
PROJECT = Path(__file__).resolve().parent.parent


def compute(data, test_mode):
    """Run the CLI, or return a deterministic result in test mode."""
    if test_mode:
        return "test-mode", ""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "src.calculator"],
            cwd=PROJECT,
            input=data,
            encoding="utf-8",
            capture_output=True,
            timeout=WORKER_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "", "calculation timed out"
    except OSError:
        return "", "could not launch calculator"
    if result.returncode:
        return "", result.stderr.strip() or "calculation failed"
    return result.stdout.strip(), ""


class Jobs:
    """Serialize storage access while computing outside the lock."""

    def __init__(self, storage, lock, clock, test_mode):
        self.storage = storage
        self.lock = lock
        self.clock = clock
        self.test_mode = test_mode
        self.queue = Queue()
        self.stopping = Event()
        self.thread = Thread(target=self.run)

    def start(self):
        with self.lock:
            for row in self.storage.search("message", {"done": PENDING}):
                self.submit(row["key"])
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.queue.put(None)
        self.thread.join()

    def submit(self, key):
        self.queue.put(key)

    def run(self):
        while not self.stopping.is_set():
            key = self.queue.get()
            if key is None:
                return
            self.process(key)

    def process(self, key):
        with self.lock:
            row = self.storage.get("message", key)
            if row is None:
                return
            self.storage.start_message(key, self.clock())
        response, failure = compute(row["data"], self.test_mode)
        with self.lock:
            if self.storage.get("message", key) is not None:
                self.storage.finish_message(
                    key,
                    {
                        "datetime": self.clock(),
                        "response": response,
                        "status": "failure" if failure else "success",
                        "failure": failure,
                    },
                )
