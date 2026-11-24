"""Locust load/soak test for the PMTiles proxy (/api/pmtiles/).

Each simulated user behaves like a browser map session: it pans to a random spot in the
Bronx and fetches a viewport of tiles through real PMTiles header and directory lookups
(cached per user, like the browser). Run it via scripts/soak_test.sh, which resolves and
confirms the target URL. There is no default host: pass --host explicitly.

Modes (SOAK_MODE): smoke (1 min, 5 users), ramp (5/20/50/100 users, 3 min each),
flat (SOAK_USERS users for SOAK_MINUTES minutes).
"""
import logging
import os
import random

import mercantile
from locust import HttpUser, LoadTestShape, between, events, task
from pmtiles.reader import Reader

logger = logging.getLogger("soak_test")

# Bronx bounding box (lon/lat) and the zooms a user browses at
BRONX = (-73.934, 40.785, -73.765, 40.915)
ZOOMS = [12, 13, 14, 15, 16, 17, 18]
VIEWPORT = (4, 3)  # tiles across, down
# Thresholds are served from both/{t}.pmtiles; t0298 is the default view
THRESHOLDS = ["t0298", "t0200", "t0400", "t0500", "t0700"]
EGRESS_USD_PER_GB = 0.12  # Cloud Run internet egress beyond the 1 GiB/month free tier


@events.init.add_listener
def require_host(environment, **_):
    if not environment.host:
        raise SystemExit("Pass --host explicitly (use scripts/soak_test.sh); there is no default.")
    logger.warning("Target: %s", environment.host)


@events.quitting.add_listener
def report_cost(environment, **_):
    total = environment.stats.total
    gb = total.total_content_length / 1024**3
    logger.warning("Requests: %d, failures: %d, downloaded: %.2f GiB (~$%.2f egress before the free 1 GiB)",
                   total.num_requests, total.num_failures, gb, gb * EGRESS_USD_PER_GB)


class MapUser(HttpUser):
    wait_time = between(1, 4)

    def on_start(self):
        self._cache = {}
        self._readers = {}

    def _reader(self, archive):
        if archive not in self._readers:
            def get_bytes(offset, length):
                key = (archive, offset, length)
                if key not in self._cache:
                    with self.client.get(
                        f"/api/pmtiles/{archive}.pmtiles",
                        headers={"Range": f"bytes={offset}-{offset + length - 1}"},
                        name="/api/pmtiles/[archive] range", catch_response=True,
                    ) as r:
                        if r.status_code != 206:
                            r.failure(f"{archive}: HTTP {r.status_code}")
                            raise RuntimeError(f"{archive}: HTTP {r.status_code}")
                        self._cache[key] = r.content
                return self._cache[key]
            self._readers[archive] = Reader(get_bytes)
        return self._readers[archive]

    def _viewport(self):
        z = random.choice(ZOOMS)
        lon = random.uniform(BRONX[0], BRONX[2])
        lat = random.uniform(BRONX[1], BRONX[3])
        t = mercantile.tile(lon, lat, z)
        return [(z, t.x + dx, t.y + dy) for dx in range(VIEWPORT[0]) for dy in range(VIEWPORT[1])]

    @task
    def pan(self):
        # 60%: Model + PLUTO view. 40%: model-only, which also reads the non-vacant and level archives.
        archives = [f"both/{random.choice(THRESHOLDS)}"]
        if random.random() < 0.4:
            archives += ["pluto_nonvacant", "model_levels"]
        for z, x, y in self._viewport():
            for archive in archives:
                try:
                    self._reader(archive).get(z, x, y)
                except Exception:
                    logger.debug("tile %s/%s/%s from %s failed", z, x, y, archive, exc_info=True)


class SoakShape(LoadTestShape):
    """(end_time_seconds, users) stages, chosen by SOAK_MODE."""

    def __init__(self):
        super().__init__()
        mode = os.environ.get("SOAK_MODE", "smoke")
        if mode == "ramp":
            self.stages = [(180, 5), (360, 20), (540, 50), (720, 100)]
        elif mode == "flat":
            self.stages = [(int(os.environ.get("SOAK_MINUTES", "10")) * 60,
                            int(os.environ.get("SOAK_USERS", "30")))]
        else:
            self.stages = [(60, 5)]

    def tick(self):
        t = self.get_run_time()
        for end, users in self.stages:
            if t < end:
                return users, 10
        return None
