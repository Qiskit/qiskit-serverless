"""The performance test driver: python -m perf {run,report,compare,export,publish,cleanup}."""

import argparse
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import export, publish, report_text, scenarios
from .cleanup import FleetDeleter, cleanup
from .config import load_config, load_metrics
from .run_dir import ROOT, RUNS, RunDir

# the gateway.limits.active_jobs_per_user Config defaults to 50
SHARED_USER_LIMIT = 50


def log(message: str) -> None:
    """Print a line with the UTC time."""
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {message}", flush=True)


@contextmanager
def _awake():
    """On macOS, keep the machine awake while the run lasts. A sleep pauses the driver and breaks the job times."""
    awake = None
    if shutil.which("caffeinate"):
        awake = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])  # pylint: disable=consider-using-with
    try:
        yield
    finally:
        if awake is not None:
            awake.terminate()


def _selected(config, only):
    selected = [s for s in config.scenarios if not only or s.name in only]
    missing = set(only or []) - {s.name for s in selected}
    if missing:
        raise SystemExit(f"Unknown scenario: {', '.join(sorted(missing))}")
    return selected


def _check(config, scenario) -> None:
    """Print the plan of one scenario, and stop when it is over the limits."""
    function, limits = config.function, config.defaults.limits
    size = scenario.function_size or function.default_size
    log(
        f"{scenario.name}: {scenario.users} users, qps {scenario.qps:g} burst {scenario.burst}: "
        f"{min(scenario.burst, scenario.users)} submit at once, the last one at {scenario.submit_seconds():.0f} s, "
        f"size {size} ({function.sizes[size]})"
    )
    # no user waits for the others' jobs, so with long jobs every job of the run can exist at once
    if scenario.users > SHARED_USER_LIMIT:
        log(
            f"  up to {scenario.users} jobs of one gateway user at once, so raise the Config "
            f"gateway.limits.active_jobs_per_user above {scenario.users} first. Otherwise submits over the limit "
            "fail and the rest stay QUEUED."
        )
    if scenario.users > limits.max_jobs or scenario.users > limits.max_users:
        raise SystemExit(
            f"{scenario.name} is over the limits: {scenario.users} users and jobs "
            f"(max {limits.max_users} users, {limits.max_jobs} jobs)"
        )


def cmd_run(args) -> None:
    """Run the scenarios in order, each in its own run directory."""
    config = load_config(args.config)
    # load metrics.yaml now, so a mistake in it stops the run before any job exists
    metrics = load_metrics(ROOT / config.defaults.sysdig.metrics) if config.defaults.sysdig else None
    selected = _selected(config, args.only)
    for scenario in selected:
        _check(config, scenario)
    if args.dry_run:
        return
    with _awake():
        for i, scenario in enumerate(selected):
            if not _cool_down(config, scenario, first=i == 0):
                log("stopped, so the scenarios after this one do not run")
                break
            if scenarios.run(config, args.config, metrics, scenario, args.keep, log, args.results):
                log("stopped, so the scenarios after this one do not run")
                break


# Code Engine refuses a new fleet with 403 quota_exceeded above this many fleets in a project
FLEET_CAP = 1000
FLEET_MARGIN = 10
ROOM_POLL_SECONDS = 30
ROOM_WAIT_SECONDS = 900


def _cool_down(config, scenario, first: bool) -> bool:
    """Wait the cooldown (not before the first scenario), then until the project has room. False on Ctrl+C."""
    try:
        if not first:
            log(f"cooldown {config.defaults.cooldown_seconds:.0f} s before {scenario.name}")
            time.sleep(config.defaults.cooldown_seconds)
        fleets = FleetDeleter(config.defaults.code_engine, log)
        if not scenario.wait_for_room:
            if (count := fleets.count()) is not None:
                log(f"the project holds {count} of {FLEET_CAP} fleets, and {scenario.name} does not wait for room")
            return True
        deadline = time.monotonic() + ROOM_WAIT_SECONDS
        while (count := fleets.count()) is not None and count + scenario.users + FLEET_MARGIN > FLEET_CAP:
            if time.monotonic() > deadline:
                log(f"the project still holds {count} fleets, so {scenario.name} may hit the {FLEET_CAP} cap")
                break
            log(f"the project holds {count} fleets, waiting for room for {scenario.users} more")
            time.sleep(ROOM_POLL_SECONDS)
        else:
            if count is not None:
                log(f"the project holds {count} of {FLEET_CAP} fleets, room for {scenario.name}")
    except KeyboardInterrupt:
        return False
    return True


def _complete(paths: list[Path]) -> list[RunDir]:
    """The run directories, and stop when one has no meta.json."""
    run_dirs = [RunDir(path) for path in paths]
    for run_dir in run_dirs:
        if not run_dir.is_complete():
            raise SystemExit(f"{run_dir.path} has no meta.json, so it is not a complete run")
    return run_dirs


def _finished() -> list[RunDir]:
    """The run directories in runs/ that got to their end, the oldest first."""
    paths = sorted(RUNS.iterdir()) if RUNS.is_dir() else []
    return [RunDir(path) for path in paths if path.is_dir() and RunDir(path).is_finished()]


def cmd_report(args) -> None:
    """Build report.txt again from a run directory."""
    run_dir = _complete([args.run_dir])[0]
    print(run_dir.write("report.txt", report_text.build(run_dir)).read_text())


def cmd_compare(args) -> None:
    """Print the main numbers of several runs side by side."""
    print(report_text.compare(_complete(args.run_dirs)))


def cmd_export(args) -> None:
    """Copy the summary of each run into the results repo, for its dashboard."""
    run_dirs = _complete(args.run_dirs)
    for run_dir in run_dirs:
        if not run_dir.is_finished():
            raise SystemExit(f"{run_dir.path} has no end_utc, so the run did not finish")
    if args.new:
        done = export.exported(args.results) | {run_dir.name for run_dir in run_dirs}
        run_dirs += [run_dir for run_dir in _finished() if run_dir.name not in done]
    if not run_dirs:
        if not args.new:
            raise SystemExit("give the run directories to export, or --new")
        log("no new finished run to export")
        return
    for path in export.export(run_dirs, args.results):
        log(f"wrote {path}")


def cmd_publish(args) -> None:
    """Export the new finished runs, then commit them and push to every remote of the results clone."""
    other = publish.blocked(args.results)
    if other:
        raise SystemExit(f"the results clone has changes export does not make: {other}. Commit or revert them first.")
    if args.dry_run:
        done = export.exported(args.results)
        todo = [run_dir.name for run_dir in _finished() if run_dir.name not in done]
        targets = ", ".join(publish.remotes(args.results)) or "no remote"
        log(f"--dry-run: would export {todo or 'no new run'}, commit them and push to {targets}")
        return
    args.run_dirs, args.new = [], True
    cmd_export(args)
    rows = publish.new_runs(args.results)
    if not rows:
        log("nothing new to publish")
        return
    for row in rows:
        numbers = row.get("numbers") or {}
        log(f"  {row['run_id']}  {row.get('release')}  DONE {numbers.get('DONE')} of {numbers.get('users')}")
    targets = ", ".join(publish.remotes(args.results)) or "no remote"
    if not args.yes and input(f"Publish {len(rows)} runs to {targets}? [y/N] ").strip().lower() != "y":
        log("nothing pushed")
        return
    publish.publish(args.results, lambda: export.write_index(args.results), log)


def cmd_cleanup(args) -> None:
    """Cancel the jobs of a run that are still active, and delete their fleets."""
    config = load_config(args.config)
    cleanup(config.defaults.gateway, config.defaults.code_engine, RunDir(args.run_dir), log)


def main() -> None:
    """The command line."""
    parser = argparse.ArgumentParser(prog="python -m perf")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the scenarios")
    run.add_argument("config", type=Path, nargs="?", default=ROOT / "scenarios.yaml")
    run.add_argument("--only", nargs="+", help="run only these scenarios")
    run.add_argument("--dry-run", action="store_true", help="print the plan and check the limits, call nothing")
    run.add_argument("--keep", action="store_true", help="leave the jobs and fleets for inspection, no cleanup")
    run.add_argument(
        "--results", type=Path, help="the clone of the results repo, each scenario is exported there when it ends"
    )
    run.set_defaults(func=cmd_run)

    report = sub.add_parser("report", help="build report.txt again from a run directory")
    report.add_argument("run_dir", type=Path)
    report.set_defaults(func=cmd_report)

    comp = sub.add_parser("compare", help="print the main numbers of several runs side by side")
    comp.add_argument("run_dirs", type=Path, nargs="+")
    comp.set_defaults(func=cmd_compare)

    exp = sub.add_parser("export", help="write the summary of runs into the results repo")
    exp.add_argument("results", type=Path, help="the clone of the results repo")
    exp.add_argument("run_dirs", type=Path, nargs="*")
    exp.add_argument("--new", action="store_true", help="also export the finished runs not yet in the results repo")
    exp.set_defaults(func=cmd_export)

    pub = sub.add_parser(
        "publish", help="export the new runs, commit them and push to every remote of the results repo"
    )
    pub.add_argument("results", type=Path, help="the clone of the results repo")
    pub.add_argument("--dry-run", action="store_true", help="show what would be published, change nothing")
    pub.add_argument("--yes", action="store_true", help="do not ask before the push")
    pub.set_defaults(func=cmd_publish)

    clean = sub.add_parser("cleanup", help="cancel the jobs of a run that are still active, and delete their fleets")
    clean.add_argument("run_dir", type=Path)
    clean.add_argument("config", type=Path, nargs="?", default=ROOT / "scenarios.yaml")
    clean.set_defaults(func=cmd_cleanup)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
