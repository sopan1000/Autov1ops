"""
AutoOps sandbox "worker" service - processes background jobs. This is the
service every chaos scenario targets (bad_deploy, oom_leak, db_exhaustion
all originate here) because that mirrors the most common real incident
shape: a background/batch service misbehaves and takes the front-facing
api down with it.

Behavior is controlled entirely by environment variables so the same
image can be deployed "good" or "broken" - see sandbox/k8s/worker-
deployment.yaml and sandbox/chaos/*.sh.
"""
import json
import logging
import os
import sys
import time

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
logger = logging.getLogger("worker")

IMAGE_TAG = os.getenv("IMAGE_TAG", "worker:v2.2")
FEATURE_X_FLAG = os.getenv("FEATURE_X_FLAG")  # deliberately unset in the bad_deploy chaos scenario
LEAK_MEMORY = os.getenv("LEAK_MEMORY", "false").lower() == "true"  # oom_leak scenario
LEAK_DB_CONNECTIONS = os.getenv("LEAK_DB_CONNECTIONS", "false").lower() == "true"  # db_exhaustion scenario

_cache = {}          # simulates the unbounded in-memory cache in oom_leak
_open_connections = []  # simulates leaked DB connections in db_exhaustion


def _log(level: str, message: str) -> None:
    getattr(logger, level)(json.dumps({"service": "worker", "image": IMAGE_TAG, "message": message}))


def process_job(job_id: str) -> None:
    if IMAGE_TAG.endswith("broken"):
        # Replays the bad_deploy scenario: this code path reads a config
        # key that was never added to the ConfigMap.
        config = {"FEATURE_X_FLAG": FEATURE_X_FLAG} if FEATURE_X_FLAG else {}
        _ = config["FEATURE_X_FLAG"]  # raises KeyError when the flag is unset - intentional

    if LEAK_MEMORY:
        _cache[job_id] = "x" * 10_000_000  # ~10MB per job, never evicted

    if LEAK_DB_CONNECTIONS:
        _open_connections.append(job_id)  # simulated handle, never released
        _log("warn", "db connection opened for batch job (connection not returned to pool on completion)")

    _log("info", f"processed job {job_id}")


def main() -> None:
    _log("info", f"worker starting, image={IMAGE_TAG}")
    i = 0
    while True:
        job_id = f"job_{8840 + i}"
        try:
            process_job(job_id)
        except KeyError as exc:
            _log("error", f"Unhandled exception processing job {job_id}: KeyError: {exc}")
        i += 1
        time.sleep(2)


if __name__ == "__main__":
    main()
