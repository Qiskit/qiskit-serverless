"""Run a piece of work in a forked child under hard operating system limits.

Bounding the cost of JSON Schema validation from inside the library meant enumerating the ways it
can be expensive, and three rounds of review found four distinct ways past that: keywords whose
cost lives in private helpers, a "$schema" at the root restoring the stock validator class when a
reference resolves, the size of a compiled regex program, and memory, which no rule bounded at all.

This bounds it from outside instead. The child gets a CPU limit and an address space limit, so
whatever it does inside, it either finishes or dies. Verified by execution: RLIMIT_CPU kills a
runaway regex at 1.00s with SIGXCPU on both macOS and Linux, and RLIMIT_AS turns a 1 GB allocation
into a catchable MemoryError at 0.38s on Linux.

The address space limit does NOT fire on macOS. It is computed at runtime from the process's own
size, plus a margin, because a fork starts out mapping everything the parent had, so an absolute
figure would need to already exceed whatever the parent happens to be using. That size comes from
``_current_address_space`` reading ``/proc/self/status``, and that file does not exist on macOS, so
the read fails there, the function returns 0, and ``_apply_limits`` skips setting RLIMIT_AS
altogether rather than set it to a wrong value. Protection therefore degrades in development and
applies in production.
"""

import json
import os
import resource
import selectors
import signal
from collections.abc import Callable
from typing import Any

_READ_CHUNK = 1 << 16

# The wall-clock deadline is derived from the CPU budget when none is passed in, by multiplying it
# rather than by adding a constant. It is not a fallback for RLIMIT_CPU but a second, independent
# bound: RLIMIT_CPU bounds how much CPU a child consumes, the deadline bounds how long it can hold
# the caller's worker while consuming it. Which of the two fires depends on how much CPU the child
# actually gets, since a child on a fraction f of a core spends its budget in budget/f wall seconds.
# The deadline's real parameter is therefore a tolerated slowdown, not a number of extra seconds, and
# adding a constant tolerates less and less as the budget grows: four seconds on top of one tolerates
# a 5x slowdown, four on top of five only 1.8x. That would make the largest configurable budget the
# least usable one, so a schema legitimately needing 3 CPU seconds would still be refused at a budget
# of 5, which is exactly what raising the budget is supposed to allow. Multiplying tolerates the same
# 5x slowdown at every budget and keeps the default deadline at the 5.0 seconds measured against the
# default 1-second budget.
#
# Past that slowdown the deadline fires first and says so, which is accurate rather than a misreport,
# and is the outcome to prefer: a child that needs 60 wall seconds to spend 5 CPU seconds (measured
# on a 16 core laptop against 40 CPU hogs, where it got 0.083 of a core) is holding a worker for a
# minute, and refusing the request beats waiting for it. In the deployed pod (3 CPU, gunicorn
# --workers=2 --threads=1) a child gets far more than a fifth of a core, so there the CPU budget is
# the bound that fires. Raising the budget is still paid for in worker occupancy either way: at the
# highest budget arguments_schema allows, one child can hold a worker for 25 wall seconds.
_WALL_CLOCK_SLOWDOWN_FACTOR = 5.0


class IsolationError(Exception):
    """Raised when isolated work did not finish within its limits."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _current_address_space() -> int:
    """Bytes of address space this process already maps, or 0 when it cannot be read."""
    try:
        with open("/proc/self/status", encoding="utf-8") as status:
            for line in status:
                if line.startswith("VmSize:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def _apply_limits(cpu_seconds: int, memory_mb: int) -> None:
    """Cap CPU and address space for this (child) process.

    The CPU soft limit raises SIGXCPU and the hard limit one second later raises SIGKILL, so a
    child that ignores the first still dies. The address space limit is the current size plus a
    margin, because a fork starts out mapping everything the parent had.
    """
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    base = _current_address_space()
    if base:
        limit = base + memory_mb * (1 << 20)
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def run_isolated(
    work: Callable[[], Any],
    *,
    cpu_seconds: int = 1,
    memory_mb: int = 128,
    wall_seconds: float | None = None,
) -> Any:
    """Run ``work`` in a forked child and return its JSON-serializable result.

    ``wall_seconds`` defaults to the CPU budget times ``_WALL_CLOCK_SLOWDOWN_FACTOR``, so that a
    raised budget is not cut short by a deadline that failed to scale with it.

    Raises:
        IsolationError: if the fork itself could not be created, the child exceeded a limit, died,
            wrote nothing, its result could not be encoded as JSON, or ``work`` raised.
    """
    if wall_seconds is None:
        wall_seconds = cpu_seconds * _WALL_CLOCK_SLOWDOWN_FACTOR
    read_fd, write_fd = os.pipe()
    try:
        pid = os.fork()
    except OSError as exc:
        # Under process-table pressure, os.fork can raise (EAGAIN et al.) instead of returning a
        # child pid. Left unhandled, that escaped run_isolated as a 500 and, worse, leaked both
        # ends of this pipe: five attempts drove the process's open file descriptors from 4 to 14.
        os.close(read_fd)
        os.close(write_fd)
        raise IsolationError(f"it could not be started: {exc}") from exc

    if pid == 0:
        # Child. Nothing here may touch the database, and it must leave through os._exit so that
        # Django's atexit handlers do not run and the connections the parent shares stay open. The
        # exit lives in a finally so that nothing between the fork and it, including a MemoryError
        # raised while encoding a large-but-successful result, can skip it.
        os.close(read_fd)
        try:
            _run_child(work, write_fd, cpu_seconds, memory_mb)
        finally:
            os._exit(0)  # pylint: disable=protected-access

    os.close(write_fd)
    try:
        return _collect(pid, read_fd, wall_seconds, cpu_seconds)
    finally:
        os.close(read_fd)


def _run_child(work: Callable[[], Any], write_fd: int, cpu_seconds: int, memory_mb: int) -> None:
    """Run ``work``, encode whatever happened, and write it to the pipe. Never raises."""
    try:
        _apply_limits(cpu_seconds, memory_mb)
        payload = {"result": work()}
    except MemoryError:
        payload = {"reason": f"it needed more than {memory_mb} MB of memory"}
    except BaseException as exc:  # pylint: disable=broad-except
        payload = {"reason": f"it raised {type(exc).__name__}"}

    try:
        encoded = json.dumps(payload).encode()
    except MemoryError:
        encoded = json.dumps({"reason": f"it needed more than {memory_mb} MB of memory"}).encode()
    except (TypeError, ValueError):
        encoded = json.dumps({"reason": "its result could not be encoded as JSON"}).encode()

    try:
        _write_all(write_fd, encoded)
    except OSError:
        pass


def _write_all(fd: int, data: bytes) -> None:
    """Write every byte of ``data``, looping past any short write.

    os.write is a single write(2), not a loop. On a blocking pipe carrying more than the 64 KB the
    pipe holds, it returns a short count when a signal arrives mid-transfer, and Python retries only
    when nothing at all was written (PEP 475), so taking the first call as complete left a valid JSON
    document cut short. The parent then read a truncated document and reported a legitimate rejection
    as the isolation having failed to produce a complete answer.

    The remainder is tracked with a memoryview rather than by slicing the bytes, so a large answer is
    not copied again inside a child that is running under a memory limit.
    """
    remaining = memoryview(data)
    while remaining:
        remaining = remaining[os.write(fd, remaining) :]


def _kill_and_reap(pid: int) -> None:
    """Make sure ``pid`` is dead and reaped, whatever state it was left in.

    Both calls tolerate failure because either can legitimately have nothing to do: the child may
    already have exited on its own (so the signal finds nothing), and a concurrent reap elsewhere
    would take the wait. What must not happen is an exception from here replacing the failure that
    brought us into this path.
    """
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        os.waitpid(pid, 0)
    except OSError:
        pass


def _read_and_reap(pid: int, read_fd: int, wall_seconds: float) -> tuple[list, bool, int, Any]:
    """Read whatever the child wrote, kill it if the deadline passed, and reap it either way.

    Returns the chunks read, whether the deadline fired, and the wait status and resource usage the
    reap reported, which is what tells a CPU overrun apart from an external kill.

    Every step lives under the try, because a failure anywhere in here used to leave the child
    running: it went on spending its CPU budget inside a worker that had already answered, and then
    sat as a zombie for the rest of that worker's life, while the failure itself escaped as the very
    500 this module exists to prevent. That is not hypothetical, and the selector is the reason. It
    is used rather than select.select because select raises ValueError on a descriptor at or above
    1024, but DefaultSelector allocates a descriptor of its own (epoll_create1), so it raises OSError
    under exactly the descriptor pressure the os.fork handler above exists for. os.read can fail the
    same way, and accumulating the chunks can run out of memory.
    """
    chunks: list = []
    reaped = False
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(read_fd, selectors.EVENT_READ)
            ready = bool(selector.select(wall_seconds))
        if ready:
            while True:
                chunk = os.read(read_fd, _READ_CHUNK)
                if not chunk:
                    break
                chunks.append(chunk)
        else:
            os.kill(pid, signal.SIGKILL)

        _, status, rusage = os.wait4(pid, 0)
        reaped = True
        return chunks, not ready, status, rusage
    except (OSError, MemoryError) as exc:
        raise IsolationError(f"its answer could not be read ({type(exc).__name__}: {exc})") from exc
    finally:
        if not reaped:
            _kill_and_reap(pid)


def _collect(pid: int, read_fd: int, wall_seconds: float, cpu_seconds: int) -> Any:
    """Read the child's answer, reap it, and turn anything else into IsolationError."""
    chunks, timed_out, status, rusage = _read_and_reap(pid, read_fd, wall_seconds)

    if not chunks:
        if timed_out:
            raise IsolationError(f"it took more than {wall_seconds} seconds of wall-clock time")
        if os.WIFSIGNALED(status):
            sig = os.WTERMSIG(status)
            # The CPU limit's hard cap also kills with SIGKILL, one second after SIGXCPU, for a
            # child that ignored the soft limit, so SIGKILL alone does not mean "CPU overrun": an
            # external SIGKILL, such as the kernel's OOM killer, arrives having spent far less than
            # the CPU budget. Telling the two apart from the signal alone is not possible, so this
            # looks at how much CPU time the child actually used instead.
            cpu_seconds_used = rusage.ru_utime + rusage.ru_stime
            if sig == signal.SIGXCPU or (sig == signal.SIGKILL and cpu_seconds_used >= cpu_seconds):
                raise IsolationError(f"it took more than {cpu_seconds} seconds of CPU time")
            if sig == signal.SIGKILL:
                raise IsolationError("it was killed by the operating system, most likely for using too much memory")
        raise IsolationError("it stopped without producing an answer")

    try:
        payload = json.loads(b"".join(chunks).decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        # A child killed mid-write (SIGKILL from the wall clock, or a hard memory limit) can leave
        # a truncated write in the pipe: valid bytes so far, but not a complete JSON document. That
        # is still the isolation failing to produce an answer, not something that should escape.
        raise IsolationError("it stopped without producing a complete answer") from exc
    if "reason" in payload:
        raise IsolationError(payload["reason"])
    return payload["result"]
