# Request size limits

Why the gateway bounds the size of a request body and of the arguments it validates, what each limit
may be set to, and how the figures behind them were measured. For the validation feature itself, see
[ARGUMENTS_VALIDATION.md](ARGUMENTS_VALIDATION.md).

## The four values

| Setting / env var | Default | Bound in code | Chart value under `gateway.application.limits` | What it bounds |
|---|---|---|---|---|
| `MAX_REQUEST_BODY_SIZE_MB` | 50 | none | `maxRequestBodySizeMb` | A JSON body or a form field, whether or not a schema is involved. Over it, `413`. Not an uploaded file, see below. |
| `MAX_ARGUMENTS_LENGTH_MB` | 32 | 64, refused above it | `maxArgumentsLengthMb` | The arguments of a function that declares a schema, checked before anything is forked. Over it, `400`. |
| `ARGUMENTS_SCHEMA_MEMORY_LIMIT_MB` | 128 | clamped to 64-256 | `argumentsSchemaMemoryLimitMb` | How much address space the validation child may add (`RLIMIT_AS`). Over it, `400`. |
| `ARGUMENTS_SCHEMA_CPU_LIMIT_SECONDS` | 1 | clamped to 1-5 | `argumentsSchemaCpuLimitSeconds` | How much CPU that child may spend (`RLIMIT_CPU`). Over it, `400`. |

`MAX_SCHEMA_LENGTH`, `MAX_DOCUMENT_DEPTH` and `MAX_SCHEMA_NODES` are plain constants in
`api/domain/arguments_schema.py` rather than settings, because no deployment has needed to move them.

## Why the body limit exists at all

`DATA_UPLOAD_MAX_MEMORY_SIZE` is **Django's own setting**, not one of ours, and it defaults to
**2.5 MB**. Django raises `RequestDataTooBig` from `HttpRequest.body` when a body is larger than that.

That default never reached a JSON request, because Django REST Framework read the request stream
directly, until **3.17.2** added this to `Request._parse`:

```python
from rest_framework.parsers import FormParser, JSONParser
if isinstance(parser, (JSONParser, FormParser)):
    stream = io.BytesIO(self.body)
```

That is not an accident to be worked around but a security fix, and making Django's limit apply to
JSON bodies was its stated purpose: **CVE-2026-73228** / [GHSA-2m8g-3cmr-wg3w](
https://github.com/encode/django-rest-framework/security/advisories/GHSA-2m8g-3cmr-wg3w), medium
severity, availability only, vulnerable `<=3.17.1` and fixed in 3.17.2. Pinning back is therefore not
an option: 3.17.1 is the last release without the behaviour and it is the vulnerable one. Note the
gap it closed had been known and tolerated since 2016 ([issue #4760](
https://github.com/encode/django-rest-framework/issues/4760)), so treat the behaviour as permanent.

`multipart/form-data` was never affected, because there Django REST Framework delegates to Django's
own parser, which is the same reason the limit still does not bound an uploaded file (see below).

From then on every JSON and form request goes through `HttpRequest.body`, and 2.5 MB is below what the
client SDK sends: it posts `/programs/run` as JSON, and one 100 qubit, depth 100 circuit is about 39 KB
of base64, so about sixty five of them reach the limit and a batch of that order fails.
`endpoint_handle_exceptions` caught the result in its generic `except Exception` and answered
`500 Internal server error`.

Measured by running the same test against each version, `POST /programs/run` with a 3 MB body:

| Django REST Framework | Function declares a schema | Result |
|---|---|---|
| 3.17.1 | no | 200, job queued |
| 3.17.2 | no | 413 once the limit is set, refused before that as a 500 |
| 3.18.0 | no | 500 `RequestDataTooBig` |
| 3.18.0 | yes | 500 `RequestDataTooBig` |

Worth knowing which version it was, because 3.17.2 was released on 2026-08-05 while this repository
pinned `djangorestframework>=3.17.1, <4`, an open range. So the change arrived on any image rebuild
from that date onwards without a single commit here, which is why the failures looked intermittent and
why they predate the explicit bump to 3.18.0. It is also two weeks before arguments validation was
merged, which is the feature they were first attributed to.

Two things made it easy to miss. The 3.17.2 notes list it under "Bug fixes" rather than as a breaking
change and do not mention the advisory, and the 3.18.0 notes do not mention it at all, so upgrading
from 3.17.1 straight to 3.18.0 and reading only the latter's notes shows nothing. And the failure
needs a JSON body over 2.5 MB, which most REST APIs never send; this one does because `/programs/run`
carries a batch of encoded circuits as arguments.

So the gateway now sets the limit itself instead of inheriting a default nobody chose, and reports
going over it as a `413` naming the limit.

### What it does not bound: uploaded files

`DATA_UPLOAD_MAX_MEMORY_SIZE` counts only the **non-file** parts of a multipart request. Verified with
the limit set to 1 KB and a 64 KB payload sent three ways:

```
multipart FILE part  -> files=['file'] size=65536
multipart FIELD part -> RequestDataTooBig
JSON body            -> RequestDataTooBig
```

So `/files/upload`, `/files/provider_upload` and `/programs/upload`, which are multipart, have no size
limit of their own from this setting: the artifact or file part goes through whatever its size.
`FILE_UPLOAD_MAX_MEMORY_SIZE` (2.5 MB, untouched here) only decides whether Django buffers a file in
memory or in a temporary file, it does not refuse anything. Bounding uploads is a separate concern and
belongs at the proxy, or in the upload views themselves; this limit does not do it, and the sizing rule
below does not cover them either.

## Why the arguments limit is smaller than the body limit

Accepting a body and validating it are different costs. Accepting one is paid once, in the worker.
Validating forks a child that parses the arguments a second time, and that child has its own two
allowances, `ARGUMENTS_SCHEMA_MEMORY_LIMIT_MB` and `ARGUMENTS_SCHEMA_CPU_LIMIT_SECONDS`.

The memory allowance bounds **address space, not resident memory**. `_apply_limits`
(`api/domain/isolated.py`) sets `RLIMIT_AS` to the parent's `VmSize` at fork time plus the margin, and
a fork inherits the parent's mappings, so a child can touch pages without mapping new ones. The two
numbers are far apart in this code path, which is why an early measurement of resident memory on macOS
overestimated the cost by a factor of two.

Measured on Linux, where `RLIMIT_AS` is actually applied ([method](#how-this-was-measured)):

| Payload shape | Address space the child adds | CPU it spends | With the defaults, refused at |
|---|---|---|---|
| Array of encoded circuits, 39 KB each | 1.0x the arguments | 0.001 s per MB | about 127 MB, by the memory margin |
| Array of tiny objects, `{"x": 1.5, "y": 2.5}` | 8.2x the arguments | 0.27 s per MB | about 3.5 MB, by the CPU budget |

Both are linear, not exponential, and the multiplier is what matters: a batch of circuits makes the child
grow by its own size, an array of small objects by eight times its size. All of that growth is
`json.loads` building a Python structure; the schema comparison itself adds nothing measurable.

With the defaults that puts three limits in a row for a batch of circuits: the length at 32 MB, the
body at 50 MB, and the margin at about 127 MB. **The length is the one that fires**, and that is the
point of it: it is checked before anything is forked, and it produces a message naming the limit
instead of a `MemoryError` in the child that the caller would read as the function's schema being
broken.

**The cap of 64 MB exists to keep that true at any configured value**, since it stays below the
margin's own 127. There is no minimum, so a deployment wanting a tighter length is free to set one.

What length cannot do is bound cost on its own, because cost follows shape. An array of small objects
is refused inside the child at about 3.5 MB, on CPU, far below any length anyone would configure. That
is the isolation doing its job, and no choice of length avoids it. For the same reason the length does
not widen what an adversarial schema can spend: the worst case for memory, an `anyOf` whose every
branch fails, costs about 208 MB per MB of arguments, so `RLIMIT_AS` refuses it at any length here.

## The validation child's two allowances

Both are read from settings by `api/domain/arguments_schema.py` and passed into `run_isolated`, which
knows only plain numeric defaults so the isolation mechanism stays free of Django. Both are clamped
before they reach the child, because a setting is also a way to weaken the protection by configuration.

### Memory, `ARGUMENTS_SCHEMA_MEMORY_LIMIT_MB` (128, clamped 64-256)

The clamp maximum guards against reopening the failure the isolation exists to close. Measured in a
container at the chart's default 2 Gi with `--workers=2 --threads=1`, a 512 MB margin let a 4 KB schema
plus 1 MB of arguments drive one child to 526 MB, and two concurrent such requests, exactly that
configuration's worker times thread concurrency, added about 960 MB to the cgroup and got a process
OOM-killed. 256 is half of the failing value.

The clamp minimum keeps it from being weakened the other way: every legitimate shape tested, including
a 1 MB batch of encoded circuits and 4000 objects under `uniqueItems`, passes at 64 MB.

**The clamp bounds one child, not the fleet of them.** The margin is per child while the pod's headroom
is per pod, so the worst case is the margin times `workers x threads`, and raising the worker count
spends the same budget that raising the margin does. The two-worker figure above therefore does not
carry over to the deployment values, which run 4Gi with five workers: there the same worst case is five
times the margin, 640 MB of 4 Gi. That is why the sizing rule below counts workers, and why whoever
changes either number should look at both together, along with the body limit.

### CPU, `ARGUMENTS_SCHEMA_CPU_LIMIT_SECONDS` (1, clamped 1-5)

Clamped more tightly than memory because this is the whole bound on how much work one request can ask
for, and no endpoint is rate limited, so raising it multiplies what a single caller can spend without
ever creating a job. Every legitimate schema measured validates in milliseconds. The minimum is 1
because `RLIMIT_CPU` counts whole seconds and 0 would kill the child immediately.

`run_isolated` derives a wall-clock deadline from this budget by multiplying it by
`_WALL_CLOCK_SLOWDOWN_FACTOR` (5.0), so a budget of 1 keeps the 5 second deadline that was measured and
a budget of 5 gets 25. The two are independent bounds rather than a limit and its fallback, and which
one fires depends on how much CPU the child actually gets: a child on a fraction of a core spends its
budget divided by that fraction in wall time. The deadline's real parameter is therefore a tolerated
slowdown, not a number of extra seconds. Adding a constant instead would tolerate less and less as the
budget grew, and would make the highest budget the least usable one: four seconds on top of one
tolerates a 5x slowdown, four on top of five only 1.8x.

Past a 5x slowdown the deadline fires first and says so, which is the outcome to prefer. Measured on a
16 core laptop against 40 CPU hogs, a child got 0.083 of a core and needed 60 wall seconds to spend 5
CPU seconds, and holding a worker for a minute is worse than refusing the request.

**The deadline has to fit inside the HTTP server's own timeout.** `gunicorn --timeout` comes from
`application.httpServer.timeout`, and its arbiter kills a worker that has not checked in for that long.
A deadline reaching the timeout means the worker is killed at the moment the gateway would have answered
`400`: a dropped connection instead of a rejection, taking every other request on that worker with it,
since the pod runs `--threads=1`. So the usable maximum depends on the deployment rather than on the
clamp: at the chart's default timeout of 25 it is a budget of 3, not 5, while the deployment values used
in staging and production set the timeout to 120, where the whole range fits. Raise the timeout before
raising the budget. This relation is not enforced in code, only documented at `_MAX_CPU_LIMIT_SECONDS`
and next to `argumentsSchemaCpuLimitSeconds` in the chart's values.

## Sizing a deployment

**A request body costs about 3.2 times its size** in the worker that holds it, because it exists three
times over at once: the bytes Django keeps, a `BytesIO` around them, and the structure `json.loads`
builds from it. Measured: 50 MB of body leaves the worker at 169 MB, 100 MB at 319 MB, 200 MB at
618 MB. **Validating adds one more copy**, in the child, so a request whose function declares a schema
costs about **4.2 times** the arguments it carries.

With `--threads=1` every worker can hold one such request at a time, so the pod needs
`resources.limits.memory` above `workers x 4.2 x maxRequestBodySizeMb`. Keeping that product under half
the pod's memory leaves the rest for the workers themselves (about 272 MB each once Django is loaded,
mostly shared because gunicorn forks them) and for everything else the gateway does.

The table gives **the largest `maxRequestBodySizeMb` that rule allows**. It is the recommendation with
the safety factor applied, not a measurement of what breaks:

| `resources.limits.memory` | `httpServer.workers: 2` | `workers: 5` | `workers: 10` |
|---|---|---|---|
| 2Gi | 120 MB | 48 MB | 24 MB |
| 4Gi | 240 MB | **96 MB** | 48 MB |
| 8Gi | 480 MB | 192 MB | 96 MB |

Production runs 4Gi with `--workers=5`, so its ceiling is 96 MB and the 50 MB default sits at about
half of it, using 26% of the pod when all five workers are validating at once. Measured in a 4 GB
container: five concurrent 50 MB bodies with validation peaked at 724 MB, and five 100 MB bodies at
1.4 GB.

Note the two limits are not independent, because the arguments travel inside the body: configuring
`maxArgumentsLengthMb` above `maxRequestBodySizeMb` achieves nothing, since the body is refused with a
`413` before anything looks at the arguments. Today that makes 50 MB the effective ceiling for
arguments, below the 64 the code would otherwise allow.

## The two ways of running out of memory are not equivalent

This is the reason the table matters, rather than just raising the limit until something breaks.

When the **child's own `RLIMIT_AS`** fires, the allocation fails, Python raises `MemoryError`, the child
catches it and reports it through its pipe, and the parent turns it into a `400`. The server carries
on and no other request is affected. This is the designed path.

When the **pod** runs out instead, the child's limit never fires, because it was never the binding
constraint. The kernel's OOM killer picks a victim by size, and that can be a gunicorn worker rather
than the child that caused the pressure. There is no `413` and no `400`: the caller gets a dropped
connection, and every request on the killed worker dies with it.

Both were observed in a single run of ten concurrent 200 MB bodies in a 4 GB container: seven requests
refused cleanly as `UnsupportedSchemaError`, and three workers killed with signal 9. So the order to
change things in is: raise the pod's memory, or lower the worker count, before raising either limit.

## Where this stops scaling

Raising the limits buys room, not a solution, and the table above says why: the cost is multiplicative
and per worker, so it is paid in RAM by every gateway pod, for data the gateway only forwards.

The reason payloads reach these sizes at all is that circuits travel **inside** the arguments. The SDK
serializes each one to QPY and base64-encodes it, because JSON cannot carry bytes, which adds 33% on
top (a 29 KB QPY becomes 39 KB). A different encoding would only shave that 33%; the body would still
have to be received and parsed.

What removes the limit rather than raising it is keeping large data out of the body: upload it with
`file_upload()` and pass the file name as an argument. Then the body is a few hundred bytes, the
gateway parses nothing, and the schema validates the reference instead of a payload it cannot inspect
anyway, since encoded circuits are opaque base64 (see the encoding section in
[ARGUMENTS_VALIDATION.md](ARGUMENTS_VALIDATION.md)). The job reads the file from COS inside its own
container, which at the default compute profile has 120 GB of memory against the 4 Gi the gateway
shares between all callers.

The pieces exist: `file_upload()` on the client, `/files/upload` accepting `application/octet-stream`
so a binary QPY needs no encoding, and job arguments already persisted to COS for Fleets. What is
missing is the convention for a vendor to declare an argument as a reference, and that is the shape to
build if payloads keep growing.

## How this was measured

### Environment

Everything about memory was measured **on Linux, in a container**, because `RLIMIT_AS` is never set on
macOS: `_current_address_space` reads `VmSize` from `/proc/self/status`, that file does not exist there,
the function returns 0, and `_apply_limits` skips the limit. Measurements of resident memory taken on
macOS do not answer the question the margin asks, and overestimated the cost by about 2x.

The container ran `jsonschema` 4.26.0 and Django 5.2.17, the versions the gateway resolves, on Python 3.11.
The gateway itself pins 3.12 (`gateway/Dockerfile`), which the recipe below uses; the measurements were taken on
3.11 and neither figure depends on the interpreter's minor version. Give the container the pod's own limits:

```bash
docker run --rm -m 4g --cpus=3 \
  -v "$PWD/gateway:/app:ro" -v "$PWD/scripts:/scripts:ro" \
  -w /app -e PYTHONPATH=/app \
  <image> python /scripts/<script>.py
```

An image is enough to build with:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir "django>=5.2" "jsonschema>=4.26,<5"
```

### Address space added by the validation child

The number the margin bounds. This forks, applies `RLIMIT_AS` the way `_apply_limits` does, and reports
how much `VmSize` the child added, so the payload size can be walked up until `MemoryError` appears.

```python
import json, os, resource, sys

def vmsize():
    with open("/proc/self/status", encoding="utf-8") as status:
        for line in status:
            if line.startswith("VmSize:"):
                return int(line.split()[1]) / 1024   # MB

target_mb, margin_mb = float(sys.argv[1]), int(sys.argv[2])
unit = {"__type__": "QuantumCircuit", "__value__": "A" * 39 * 1024}
count = max(1, int(target_mb * 1024 * 1024 / len(json.dumps(unit))))
arguments_str = json.dumps({"circuits": [unit] * count})

read_fd, write_fd = os.pipe()
if os.fork() == 0:
    os.close(read_fd)
    base = vmsize()
    limit = int(base * 1024 * 1024) + margin_mb * (1 << 20)
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    try:
        parsed = json.loads(arguments_str)
        result = f"grew {vmsize() - base:.0f} MB, ok"
    except MemoryError:
        result = f"grew {vmsize() - base:.0f} MB, MemoryError"
    os.write(write_fd, result.encode())
    os.close(write_fd)
    os._exit(0)
os.close(write_fd)
print(f"{len(arguments_str)/1024/1024:.1f} MB args, margin {margin_mb}: {os.read(read_fd, 4096).decode()}")
os.wait()
```

Swap the payload for `{"points": [{"x": i + 0.5, "y": i + 1.5} for i in range(count)]}` to get the
second row of the shape table.

Results at the default 128 MB margin: circuits grew the child by as much as the arguments weighed, up to
100 MB, and raised `MemoryError` at 128 MB; tiny objects grew it 8.2 times their own size, up to 12.6 MB
of arguments, and raised `MemoryError` at 19 MB.

### End to end verdict and CPU, through the real entry point

Same container, calling what the use case calls, to see which limit fires first and what the caller
would get. Run one process per point so `ru_maxrss` reflects only that measurement.

```python
import json, os, resource, sys
from django.conf import settings

settings.configure(
    ARGUMENTS_SCHEMA_MEMORY_LIMIT_MB=int(os.environ.get("MARGIN_MB", "128")),
    ARGUMENTS_SCHEMA_CPU_LIMIT_SECONDS=1,
)
from api.domain.arguments_schema import validate_arguments_in_isolation

# ... build schema and arguments_str for the shape and size under test ...
before = resource.getrusage(resource.RUSAGE_CHILDREN)
try:
    validate_arguments_in_isolation(schema, arguments_str)
    verdict = "accepted"
except Exception as exc:
    verdict = type(exc).__name__
after = resource.getrusage(resource.RUSAGE_CHILDREN)
cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
print(f"{verdict}, child rss {after.ru_maxrss/1024:.0f} MB, cpu {cpu:.2f}s")
```

This is where the CPU column comes from. Walk the size up to bracket the threshold rather than reporting
the first size that fails, which is how an earlier version of this document got it wrong by almost 2x:
tiny objects at 1.5 MB spent 0.42 s and at 3.0 MB spent 0.82 s, both accepted, while 3.8 MB was cut with
`it took more than 1 seconds of CPU time`. So the budget runs out at about 3.5 MB, consistent with the
0.27 s per MB the accepted runs show. For comparison, 100 MB of circuits spends 0.10 s.

### Pod behaviour at full concurrency

The run that produced the `SIGKILL` output above. It forks one process per worker, and each does what a
request does: hold the body as bytes, copy it, parse it, then validate. Reading `/sys/fs/cgroup/memory.current`
gives what the container is charged, and checking `os.waitpid`'s status for a signal is what tells an
OOM kill apart from a clean rejection.

```python
pid = os.fork()
# ... in the child: build a body of BODY_MB, bytes(body), json.loads, then
#     validate_arguments_in_isolation(SCHEMA, parsed["arguments"]) ...
_, status = os.waitpid(pid, 0)
if status & 0x7F:
    print(f"worker killed by signal {status & 0x7F}")   # 9 is the OOM killer
```

Run it as `WORKERS x BODY_MB`: 5 x 50 and 5 x 100 both passed in a 4 GB container, 10 x 200 produced
three OOM kills and seven clean rejections.

### Repeating any of this after a change

The figures worth re-checking if `jsonschema`, Django or Django REST Framework move: that a batch of circuits grows the
child by its own size and no more (it
is the one the margin is chosen against), the 3.2x body cost, and that a body over the limit still
comes back as `413` rather than `500`. The last one is covered by
`gateway/tests/api/test_request_body_size.py` and needs no container.
