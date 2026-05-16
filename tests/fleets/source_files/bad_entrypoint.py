"""Bad entrypoint that always fails — used to test the error path."""

# The [public] prefix is required so the log-filtering awk pipeline
# writes this line to the user log file (SECONDARY_LOG_PATH).
# Without it the message only appears in provider logs.
print("[public] Intentional failure for testing", flush=True)
raise RuntimeError("Intentional failure for testing")
