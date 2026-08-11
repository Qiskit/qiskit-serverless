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
    wall_seconds: float = 5.0,
) -> Any:
    """Run ``work`` in a forked child and return its JSON-serializable result.

    Raises:
        IsolationError: if the fork itself could not be created, the child exceeded a limit, died,
            wrote nothing, its result could not be encoded as JSON, or ``work`` raised.
    """
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
        os.write(write_fd, encoded)
    except OSError:
        pass


def _collect(pid: int, read_fd: int, wall_seconds: float, cpu_seconds: int) -> Any:
    """Read the child's answer, reap it, and turn anything else into IsolationError."""
    chunks = []
    # selectors picks epoll/kqueue/poll under the hood rather than select.select, which raises
    # ValueError on a descriptor at or above 1024: under fd pressure that would escape as a 500 and
    # leave the child unreaped.
    with selectors.DefaultSelector() as selector:
        selector.register(read_fd, selectors.EVENT_READ)
        ready = bool(selector.select(wall_seconds))
    timed_out = not ready
    if ready:
        while True:
            chunk = os.read(read_fd, _READ_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
    else:
        os.kill(pid, signal.SIGKILL)

    _, status, rusage = os.wait4(pid, 0)

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
