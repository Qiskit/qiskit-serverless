"""Commit the exported runs in the results repo and push them to every remote of that clone."""

import json
import subprocess
from pathlib import Path


def _git(results: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", "-C", str(results), *args], capture_output=True, text=True, check=False)
    if check and done.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done


def _changed(results: Path) -> list[tuple[str, str]]:
    """(status code, path) of every file git sees as changed, new or deleted."""
    return [(line[:2], line[3:]) for line in _git(results, "status", "--porcelain", "-uall").stdout.splitlines()]


def blocked(results: Path) -> list[str]:
    """Changes export does not make: outside runs/, or a deleted or renamed file. Publish leaves them to the person."""
    return [path for code, path in _changed(results) if not path.startswith("runs/") or "D" in code or "R" in code]


def new_runs(results: Path) -> list[dict]:
    """The index rows of the runs that are not committed yet."""
    paths = [path for _, path in _changed(results)]
    index = json.loads((results / "runs" / "index.json").read_text())
    return [row for row in index if any(path.startswith(f"runs/{row['run_id']}/") for path in paths)]


def remotes(results: Path) -> list[str]:
    """The remotes publish pushes to."""
    return _git(results, "remote").stdout.split()


def publish(results: Path, rebuild_index, log) -> None:
    """Commit runs/, then pull and push each remote. A conflict on runs/index.json is solved by rebuilding it."""
    rows = new_runs(results)
    releases = sorted({row.get("release") or "unknown" for row in rows})
    _git(results, "add", "runs")
    if _git(results, "diff", "--cached", "--quiet", check=False).returncode:
        _git(
            results,
            "commit",
            "-s",
            "-q",
            "-m",
            f"Add {len(rows)} run{'s' if len(rows) != 1 else ''} of release {', '.join(releases)}",
        )
    branch = _git(results, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    for remote in remotes(results):
        # an empty remote has no branch to pull from yet
        if _git(results, "ls-remote", "--heads", remote, branch).stdout.strip():
            pulled = _git(results, "pull", "--rebase", "-q", remote, branch, check=False)
            if pulled.returncode:
                conflicts = _git(results, "diff", "--name-only", "--diff-filter=U").stdout.split()
                if conflicts != ["runs/index.json"]:
                    _git(results, "rebase", "--abort", check=False)
                    raise SystemExit(f"{remote}: the pull failed, conflicts {conflicts}: {pulled.stderr.strip()}")
                # every run has its own folder, so only the index can conflict, and it is rebuilt from the folders
                rebuild_index()
                _git(results, "add", "runs/index.json")
                _git(results, "-c", "core.editor=true", "rebase", "--continue")
        _git(results, "push", "-q", remote, branch)
        log(f"pushed {branch} to {remote}")
