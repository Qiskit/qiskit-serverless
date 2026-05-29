"""Entrypoint that generates log output exceeding the configured size limit."""

from qiskit_serverless import get_arguments, save_result


def main():
    """Write numbered lines totaling ~150KB, well beyond the 50KB test limit."""
    args = get_arguments()
    target_bytes = args.get("target_bytes", 150000)

    written = 0
    line_num = 0
    while written < target_bytes:
        line_num += 1
        line = f"[public] LOG_LINE_{line_num:06d} padding={'x' * 60}"
        print(line)
        written += len(line) + 1

    print(f"[public] FINAL_LINE total_lines={line_num} total_bytes={written}")
    save_result({"total_lines": line_num, "total_bytes": written, "status": "completed"})


if __name__ == "__main__":
    main()
