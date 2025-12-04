import logging


class PrefixFormatter(logging.Formatter):
    def __init__(self, prefix, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefix = prefix

    def format(self, record):
        original_msg = record.getMessage()
        lines = original_msg.splitlines()

        formatted_lines = []
        for line in lines:
            temp = logging.LogRecord(
                name=record.name,
                level=record.levelno,
                pathname=record.pathname,
                lineno=record.lineno,
                msg=line,
                args=None,
                exc_info=None,
            )

            base = super().format(temp)
            formatted_lines.append(f"{self.prefix} {base}")

        return "\n".join(formatted_lines)


def _create_logger(name, prefix):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = PrefixFormatter(
            prefix=prefix, fmt="%(levelname)s:%(name)s: %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def get_logger():
    return _create_logger("user", "[PUBLIC]")


def get_provider_logger():
    return _create_logger("provider", "[PRIVATE]")
