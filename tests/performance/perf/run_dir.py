"""The files of one run, in runs/<UTC time>-<scenario>/. Every module reads and writes them through RunDir."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"


class RunDir:
    """One run directory. A jsonl file reads back every whole line, so a line cut by a killed run is skipped."""

    def __init__(self, path: Path):
        self.path = path
        self.calls = path / "calls.jsonl"
        self.health = path / "health.jsonl"
        self._lock = threading.Lock()

    @classmethod
    def create(cls, scenario: str) -> "RunDir":
        """A new, empty run directory named after the UTC time and the scenario."""
        path = RUNS / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{scenario}"
        path.mkdir(parents=True)
        return cls(path)

    @property
    def name(self) -> str:
        """The run id."""
        return self.path.name

    def is_complete(self) -> bool:
        """Whether the run got as far as writing meta.json."""
        return (self.path / "meta.json").exists()

    def is_finished(self) -> bool:
        """Whether the run got to its end, so meta.json has end_utc."""
        return bool(self.read("meta.json").get("end_utc"))

    def read(self, name: str) -> list[dict] | dict:
        """A jsonl file as a list of rows, or a json file as a dict. A missing file is empty."""
        path = self.path / name
        if name.endswith(".jsonl"):
            if not path.exists():
                return []
            rows = []
            for line in path.read_text().splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
            return rows
        return json.loads(path.read_text()) if path.exists() else {}

    def write(self, name: str, data: list[dict] | dict | str) -> Path:
        """Write rows as jsonl, a dict as json, or text as it is."""
        path = self.path / name
        if isinstance(data, str):
            path.write_text(data)
        elif name.endswith(".jsonl"):
            path.write_text("".join(json.dumps(row) + "\n" for row in data))
        else:
            path.write_text(json.dumps(data, indent=1))
        return path

    def append_job_id(self, user: int, job_id: str) -> None:
        """Append one job id to job_ids.jsonl as soon as run() returns, so a killed run still leaves it."""
        with self._lock, (self.path / "job_ids.jsonl").open("a") as file:
            file.write(json.dumps({"user": user, "job_id": job_id}) + "\n")

    def job_ids(self) -> list[str]:
        """Every job id of the run, from users.jsonl and job_ids.jsonl."""
        rows = self.read("users.jsonl") + self.read("job_ids.jsonl")
        return sorted({row["job_id"] for row in rows if row.get("job_id")})

    def copy_in(self, source: Path, name: str) -> None:
        """Keep a copy of a file that ran, like scenarios.yaml."""
        (self.path / name).write_bytes(source.read_bytes())
