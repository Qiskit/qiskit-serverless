"""Runs every query of metrics.yaml against the IBM Cloud Monitoring (Sysdig) Prometheus API."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import Metrics, Sysdig
from . import iam

# how long to wait for Sysdig to store the samples of the end of the run
INGEST_WAIT_SECONDS = 300
INGEST_POLL_SECONDS = 10
# the scheduler metrics are scraped about once a minute, so wait one more scrape past the end of the run
SCRAPE_SECONDS = 60


class _Api:  # pylint: disable=too-few-public-methods
    """GET on the Prometheus API of one instance."""

    def __init__(self, sysdig: Sysdig, token: str):
        self._base = f"https://{sysdig.region}.monitoring.cloud.ibm.com/prometheus/api/v1"
        self._headers = {"Authorization": f"Bearer {token}", "IBMInstanceID": sysdig.instance_id}

    def get(self, path: str, **params) -> dict:
        """The decoded JSON answer."""
        request = urllib.request.Request(f"{self._base}/{path}?{urllib.parse.urlencode(params)}", headers=self._headers)
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)


def _clock(api: _Api, sysdig: Sysdig) -> dict:
    """The Sysdig clock against this laptop's, and the time of the newest sample of the cluster."""
    sent = time.time()
    body = api.get("query", query="time()")
    received = time.time()
    offset = float(body["data"]["result"][0]) - (sent + received) / 2
    body = api.get(
        "query", query=f'max(timestamp(kube_pod_container_status_ready{{kube_cluster_name="{sysdig.cluster}"}}))'
    )
    result = body["data"]["result"]
    newest = float(result[0]["value"][1]) - offset if result else None
    return {"offset_seconds": offset, "newest_sample": newest, "round_trip_seconds": received - sent}


def _wait_for_samples(api: _Api, sysdig: Sysdig, end: float, log) -> dict:
    """Wait until Sysdig has stored a sample one scrape past the end of the run, up to INGEST_WAIT_SECONDS."""
    deadline = time.time() + INGEST_WAIT_SECONDS
    while True:
        clock = _clock(api, sysdig)
        if clock["newest_sample"] is not None and clock["newest_sample"] >= end + SCRAPE_SECONDS:
            return clock
        if time.time() >= deadline:
            log(
                f"Sysdig has no sample one scrape after the end of the run after {INGEST_WAIT_SECONDS} s, "
                "so the end of the run may be missing"
            )
            return clock
        time.sleep(INGEST_POLL_SECONDS)


def collect(sysdig: Sysdig, metrics: Metrics, start: float, end: float, log) -> dict:
    """{name: {"query": ..., "result": [...]} or {"error": ...}} for the run window, and "_clock" with the offset.

    The window ends at the newest sample Sysdig has stored, so it never asks for samples that do not exist yet.
    """
    key = iam.api_key()
    if not key:
        log("no IBM_CLOUD_API_KEY, so no Sysdig metrics")
        return {}
    try:
        api = _Api(sysdig, iam.token(key))
        clock = _wait_for_samples(api, sysdig, end, log)
    except (OSError, ValueError, KeyError, IndexError) as exc:
        log(f"no Sysdig metrics, the API failed: {type(exc).__name__}: {exc}")
        return {}
    log(f"Sysdig clock is {clock['offset_seconds']:+.2f} s from this laptop")
    # the run and one scrape after it, so a peak or a total never includes the scenario before
    clock["window_start"] = start
    clock["window_end"] = min(end + SCRAPE_SECONDS, clock["newest_sample"] or end)
    out: dict = {"_clock": clock}
    # Sysdig times are its own clock, so shift the driver's window by the offset
    window = {
        "start": int(clock["window_start"] + clock["offset_seconds"]),
        "end": int(clock["window_end"] + clock["offset_seconds"]),
        "step": metrics.step_seconds,
    }
    for metric in metrics.metrics:
        query = metric.query.replace("{cluster}", sysdig.cluster).replace("{namespace}", metrics.namespace)
        try:
            if metric.read == "last":
                result = _total(api, query, window["start"], window["end"])
            else:
                result = api.get("query_range", query=query, **window).get("data", {}).get("result", [])
            out[metric.name] = {"query": query, "read": metric.read, "result": result}
        except urllib.error.HTTPError as exc:
            out[metric.name] = {
                "query": query,
                "error": f"HTTP {exc.code}: {exc.read()[:300].decode(errors='replace')}",
            }
        except (OSError, ValueError) as exc:
            out[metric.name] = {"query": query, "error": f"{type(exc).__name__}: {exc}"}
        if not out[metric.name].get("result"):
            log(f"sysdig {metric.name}: no data")
    return out


def _total(api: _Api, query: str, start: int, end: int) -> list[dict]:
    """A counter's total over the run: its value at the end minus at the start, in the query_range format.

    A series that is new in the run starts at 0, and a counter that went down was reset, so its total is its end value.
    """

    def instant(at: int) -> dict:
        result = api.get("query", query=query, time=at).get("data", {}).get("result", [])
        return {json.dumps(r["metric"], sort_keys=True): float(r["value"][1]) for r in result}

    # Sysdig answers a past instant from a one-minute sample, so read the start one scrape before it
    before, after = instant(start - SCRAPE_SECONDS), instant(end)
    out = []
    for key, value in after.items():
        total = value - before.get(key, 0.0)
        out.append({"metric": json.loads(key), "values": [[end, str(value if total < 0 else total)]]})
    return out
