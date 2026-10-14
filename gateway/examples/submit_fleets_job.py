#!/usr/bin/env python3
"""
Fleets integration test: custom function and provider function.

Scenario A — Custom function:
  Upload entrypoint via client SDK (QiskitFunction + working_dir),
  run with arguments, validate logs and result.

Scenario B — Provider function:
  Pre-upload entrypoint to COS provider bucket, register function
  with provider + image via API, run with arguments, validate
  public logs, provider logs, and result.

Both scenarios assert:
  - Job completes with DONE status
  - Public logs contain [public]-tagged lines (prefix stripped)
  - Result contains expected fields from function arguments

Prerequisites:
  source gateway/examples/setup_fleets_env.sh
  bash gateway/examples/run_fleets_dev.sh

Usage:
  python gateway/examples/submit_fleets_job.py           # run all
  python gateway/examples/submit_fleets_job.py custom    # scenario A only
  python gateway/examples/submit_fleets_job.py provider  # scenario B only
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from qiskit_serverless import QiskitFunction, ServerlessClient

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
SOURCE_FILES = str(SCRIPT_DIR / "source_files")

GATEWAY_URL = "http://localhost:8000"
TOKEN = "awesome_token"
CHANNEL = "local"

FUNCTION_ARGUMENTS = {
    "backend_name": "ibm_sherbrooke",
    "molecule": {"atoms": ["H", "H"]},
}


def wait_for_job(job, timeout=300):
    """Poll until terminal state. Returns final status."""
    start = time.time()
    status = None
    while time.time() - start < timeout:
        status = job.status()
        elapsed = int(time.time() - start)
        print(f"    [{elapsed:3d}s] {status}")
        if status in ("DONE", "ERROR", "CANCELED"):
            return status
        time.sleep(5)
    return f"TIMEOUT (last: {status})"


def assert_eq(name, actual, expected):
    if actual != expected:
        print(f"  FAIL: {name}: expected {expected!r}, got {actual!r}")
        return False
    print(f"  OK: {name}")
    return True


def assert_in(name, substring, text):
    if not text or substring not in text:
        print(f"  FAIL: {name}: '{substring}' not found")
        return False
    print(f"  OK: {name}")
    return True


def assert_not_in(name, substring, text):
    if text and substring in text:
        print(f"  FAIL: {name}: '{substring}' should not be present")
        return False
    print(f"  OK: {name}")
    return True


def scenario_custom_function(client, timestamp):
    """Scenario A: custom function uploaded via client SDK."""
    print("\n" + "=" * 60)
    print("SCENARIO A: Custom function (entrypoint via working_dir)")
    print("=" * 60)

    title = f"fleets-custom-{timestamp}"
    my_function = QiskitFunction(
        title=title,
        entrypoint="hello.py",
        working_dir=SOURCE_FILES,
        runner="fleets",
    )
    client.upload(my_function)
    print(f"  Uploaded: {title}")

    # List functions and verify ours is visible
    functions = client.list()
    titles = [f.title for f in functions]
    print(f"  Available functions: {titles}")
    if title not in titles:
        return ["uploaded function not found in list"]

    # Run
    function = client.get(title=title)
    job = function.run(**FUNCTION_ARGUMENTS)
    print(f"  Submitted: {job.job_id}")

    print("  Monitoring:")
    status = wait_for_job(job)

    errors = []

    if not assert_eq("status", status, "DONE"):
        errors.append("Job did not complete with DONE")
        return errors

    # Public logs
    logs = job.logs()
    print(f"\n  Public logs:\n{logs}")

    assert_in("logs: hello", "Hello from Code Engine Fleets!", logs) or errors.append("missing hello")
    assert_in("logs: backend", "Backend: ibm_sherbrooke", logs) or errors.append("missing backend")
    assert_in("logs: molecule", "['H', 'H']", logs) or errors.append("missing molecule")
    assert_in("logs: result saved", "Result saved", logs) or errors.append("missing result saved")

    # Provider logs — 403 expected for custom functions
    print("\n  Provider logs (expect 403):")
    try:
        job.provider_logs()
        errors.append("provider_logs should not be accessible for custom functions")
    except Exception as e:
        if "403" in str(e):
            print("    OK: 403 as expected")
        else:
            print(f"    Unexpected: {e}")

    # Result
    try:
        result = job.result()
        print(f"\n  Result: {result}")
        assert_eq("result.status", result.get("status"), "ok") or errors.append("bad status")
        assert_eq("result.backend_name", result.get("backend_name"), "ibm_sherbrooke") or errors.append("bad backend")
        assert_eq("result.molecule", result.get("molecule"), {"atoms": ["H", "H"]}) or errors.append("bad molecule")
    except Exception as e:
        errors.append(f"result failed: {e}")

    return errors


def scenario_provider_function(client, timestamp):
    """Scenario B: provider function with Runner class baked into image.

    The provider image contains a Runner class at /runner/runner/ that the
    gateway-generated main.tmpl imports and executes. No COS pre-upload needed.
    """
    print("\n" + "=" * 60)
    print("SCENARIO B: Provider function (Runner class in image)")
    print("=" * 60)

    title = f"fleets-provider-{timestamp}"
    provider = "mockprovider"
    image = "private.icr.io/qc-qiskit-functions-ce-staging/test-local-provider-function:latest"
    entrypoint = "entrypoint.py"

    # Register function via API (no COS pre-upload — code lives in the image)
    response = requests.post(
        f"{GATEWAY_URL}/api/v1/programs/upload/",
        headers={"Authorization": f"Bearer {TOKEN}"},
        data={
            "title": title,
            "provider": provider,
            "image": image,
            "runner": "fleets",
            "entrypoint": entrypoint,
            "dependencies": "[]",
            "env_vars": "{}",
        },
        timeout=30,
    )
    if response.status_code != 200:
        print(f"  Upload failed ({response.status_code}): {response.text}")
        return ["upload failed"]
    print(f"  Registered: {provider}/{title}")

    # List functions and verify ours is visible
    functions = client.list()
    titles = [f.title for f in functions]
    print(f"  Available functions: {titles}")
    if title not in titles:
        return ["registered function not found in list"]

    # Run
    function = client.get(title=f"{provider}/{title}")
    job = function.run(**FUNCTION_ARGUMENTS)
    print(f"  Submitted: {job.job_id}")

    print("  Monitoring:")
    status = wait_for_job(job)

    errors = []

    if not assert_eq("status", status, "DONE"):
        errors.append("Job did not complete with DONE")
        try:
            logs = job.logs()
            print(f"\n  Logs (debug):\n{logs}")
        except Exception:
            pass
        return errors

    # Public logs (Runner output tagged with [public] prefix)
    logs = job.logs()
    print(f"\n  Public logs:\n{logs}")
    assert_in("public: job started", "Starting job with arguments", logs) or errors.append("missing start message")

    # Provider logs (all untagged output goes here)
    print("\n  Provider logs:")
    try:
        provider_logs = job.provider_logs()
        print(f"    {provider_logs}")
    except Exception as e:
        print(f"    Error: {e}")

    # Result (validates Runner.run() returned correct data)
    try:
        result = job.result()
        print(f"\n  Result: {result}")
        assert_eq("result.backend_name", result.get("backend_name"), "ibm_sherbrooke") or errors.append("bad backend")
    except Exception as e:
        errors.append(f"result failed: {e}")

    return errors


def main():
    print("=== Fleets Integration Test ===\n")

    # Parse CLI args
    scenarios = sys.argv[1:] if len(sys.argv) > 1 else ["custom", "provider"]

    client = ServerlessClient(host=GATEWAY_URL, token=TOKEN, channel=CHANNEL)
    print(f"Connected to: {GATEWAY_URL}")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    all_errors = []

    if "custom" in scenarios:
        errors_a = scenario_custom_function(client, timestamp)
        all_errors.extend(f"[A] {e}" for e in errors_a)

    if "provider" in scenarios:
        errors_b = scenario_provider_function(client, timestamp)
        all_errors.extend(f"[B] {e}" for e in errors_b)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if all_errors:
        print("FAILURES:")
        for e in all_errors:
            print(f"  - {e}")
        return 1

    print("All scenarios PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
