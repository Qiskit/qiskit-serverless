"""Runs a scenario: every user uploads, then they submit through one rate limiter, and no one waits for the others."""

import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from qiskit_serverless.version import __version__ as client_version

from . import export, logs, report_text, sysdig
from .cleanup import FleetDeleter, cleanup
from .config import Config, Metrics, Scenario
from .health import HealthSampler
from .jobs import collect_jobs
from .progress import Progress
from .rate_limit import RateLimiter
from .stats import job_numbers
from .run_dir import ROOT, RunDir
from .tracer import Tracer
from .users import User, UserResult, function_for_upload

# a user that waits longer than this gives up on its job
JOB_TIMEOUT_SECONDS = 4 * 3600
# after a stop, how long to wait for the users to return before the run goes on to the cleanup
STOP_WAIT_SECONDS = 60


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    config: Config,
    config_path: Path,
    metrics: Metrics | None,
    scenario: Scenario,
    keep: bool,
    log,
    results: Path | None = None,
) -> bool:
    """One scenario from start to end: the users, the traces, the job data, Sysdig, the report, the cleanup, and the
    export into the results repo when `results` is set.

    Returns True when a signal stopped it. Once jobs exist, each later step logs its own error and the cleanup
    still runs, so a failure there cannot leave fleets behind.
    """
    run_dir = RunDir.create(scenario.name)
    run_dir.copy_in(config_path, "scenarios.yaml")
    if config.defaults.sysdig:
        run_dir.copy_in(ROOT / config.defaults.sysdig.metrics, "metrics.yaml")
    log(f"run {run_dir.name}, output in {run_dir.path}")
    start = time.time()
    meta = {
        "run_id": run_dir.name,
        "scenario": scenario.name,
        "gateway": config.defaults.gateway,
        "start_utc": datetime.fromtimestamp(start, timezone.utc).isoformat(),
        "end_utc": None,
        "git_sha": _git_sha(),
        "client_version": client_version,
        "poll_seconds": config.defaults.poll_seconds,
        "poll": scenario.poll,
        "qps": scenario.qps,
        "burst": scenario.burst,
        "planned_submit_seconds": scenario.submit_seconds(),
    }
    run_dir.write("meta.json", meta)

    deleter = FleetDeleter(None if keep else config.defaults.code_engine, log)
    tracer, health = Tracer(run_dir.calls), HealthSampler(run_dir.health)
    tracer.start()
    health.start()
    users = Run(config, scenario, run_dir, deleter, log)
    # the signal handlers stay until the cleanup ends, so a second Ctrl+C cannot skip it
    with users:
        try:
            users.wait()
        finally:
            end = time.time()
            tracer.stop()
            health.stop()
            run_dir.write("users.jsonl", users.rows())
            meta["end_utc"] = datetime.fromtimestamp(end, timezone.utc).isoformat()
            run_dir.write("meta.json", meta)
            _try(
                log,
                "read the jobs",
                lambda: run_dir.write("jobs.jsonl", collect_jobs(config.defaults.gateway, users.rows(), log)),
            )
            if config.defaults.sysdig and metrics is not None:
                _try(
                    log,
                    "read Sysdig",
                    lambda: run_dir.write(
                        "sysdig.json", sysdig.collect(config.defaults.sysdig, metrics, start, end, log)
                    ),
                )
            if config.defaults.cloud_logs:
                _try(
                    log,
                    "read the submit times",
                    lambda: run_dir.write(
                        "submits.jsonl",
                        logs.submit_times(config.defaults.cloud_logs, run_dir.job_ids(), start, end, log),
                    ),
                )
            _try(log, "write the report", lambda: run_dir.write("report.txt", report_text.build(run_dir)))
            if keep:
                log(f"--keep: the jobs and fleets are left. Run cleanup {run_dir.path} later.")
            else:
                _try(
                    log,
                    "cancel the jobs that are still active and delete their fleets",
                    lambda: cleanup(config.defaults.gateway, config.defaults.code_engine, run_dir, log),
                )
            if results and not users.stopped:
                _try(log, f"export to {results}", lambda: export.export([run_dir], results))
    log(_summary(scenario.name, run_dir.read("users.jsonl"), run_dir.path / "report.txt"))
    return users.stopped


def _try(log, name: str, step) -> None:
    """Run one step after the users. A failure is logged, so the steps after it and the cleanup still run."""
    log(name)
    try:
        step()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log(f"could not {name}: {type(exc).__name__}: {exc}")


def _summary(name: str, users: list[dict], report: Path) -> str:
    """The last line of a scenario, for example "result burst: 18 DONE, 2 failed, 5 failed status checks"."""
    job = job_numbers(users, [])
    done = job["final"].get("DONE", 0)
    return (
        f"result {name}: {done} DONE, {job['users'] - done} failed, {job['failed_polls'] or 0} failed status checks, "
        f"report {report}"
    )


class Run:  # pylint: disable=too-many-instance-attributes
    """The users of one scenario. As a context it handles Ctrl+C and SIGTERM, and removes the function copies.

    A signal stops the users and lets them return what they saw, so the run is still written.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, config: Config, scenario: Scenario, run_dir: RunDir, deleter: FleetDeleter, log
    ):
        self._config = config
        self._deleter = deleter
        self._scenario = scenario
        self._run_dir = run_dir
        self._log = log
        self._stop = threading.Event()
        # every user uploads first, so the upload time does not slow the rate of the submits.
        # A stop breaks it, so the users waiting on it return at once.
        self._ready = threading.Barrier(scenario.users)
        self._limiter = RateLimiter(scenario.qps, scenario.burst)
        self._results: list[UserResult] = []
        self._threads: list[threading.Thread] = []
        self._previous: dict = {}
        # one folder per user: the client writes and deletes artifact.tar in working_dir
        self._copies = Path(tempfile.mkdtemp(prefix="perf-functions-"))

    def __enter__(self) -> "Run":
        self._previous = {sig: signal.signal(sig, self._on_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
        return self

    def __exit__(self, *_) -> None:
        shutil.rmtree(self._copies, ignore_errors=True)
        for sig, handler in self._previous.items():
            signal.signal(sig, handler)

    @property
    def stopped(self) -> bool:
        """Whether a signal stopped the users."""
        return self._stop.is_set()

    def _on_signal(self, signum, _frame) -> None:
        self._log(f"{signal.Signals(signum).name}: stopping the users, then the run cleans up and stops")
        self._stop.set()
        self._ready.abort()

    def wait(self) -> None:
        """Start every user, and wait until all of them are done."""
        self._add_users()
        progress = Progress(self._results, self._log)
        progress.start()
        for thread in self._threads:
            thread.start()
        stopped_at = None
        try:
            # a short timeout, so the main thread sees a signal at once
            while any(thread.is_alive() for thread in self._threads):
                if self._stop.is_set():
                    stopped_at = stopped_at or time.monotonic()
                    if time.monotonic() - stopped_at > STOP_WAIT_SECONDS:
                        # a user stuck in a call: it is a daemon thread, so it ends with the process
                        self._log(f"some users did not stop in {STOP_WAIT_SECONDS} s, so the run goes on without them")
                        break
                for thread in self._threads:
                    thread.join(timeout=0.5)
        finally:
            progress.stop()

    def rows(self) -> list[dict]:
        """One row per user."""
        return [{"run_id": self._run_dir.name, "scenario": self._scenario.name, **asdict(r)} for r in self._results]

    def _add_users(self) -> None:
        function, defaults = self._config.function, self._config.defaults
        arguments = {**self._scenario.arguments, "function_size": self._scenario.function_size or function.default_size}
        for i in range(self._scenario.users):
            working_dir = self._copies / f"u{i:03d}"
            shutil.copytree(ROOT / function.path, working_dir)
            title = f"{function.title}-u{i:03d}"
            user = User(
                gateway=defaults.gateway,
                user=i,
                upload=function_for_upload(function, str(working_dir), title),
                arguments=arguments,
                poll_seconds=defaults.poll_seconds,
                backoff=self._scenario.poll == "backoff",
                timeout_seconds=JOB_TIMEOUT_SECONDS,
                ready=self._ready,
                limiter=self._limiter,
                stop=self._stop,
                on_job=self._run_dir.append_job_id,
                delete_fleet=self._deleter.delete,
            )
            self._results.append(UserResult(user=i))
            self._threads.append(
                threading.Thread(target=user.run, args=(self._results[-1],), name=f"user-{i}", daemon=True)
            )
