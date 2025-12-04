import logging

class PrefixFormatter(logging.Formatter):
    def __init__(self, prefix, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefix = prefix

    def formatMessage(self, record):
        original_message = super().formatMessage(record)
        return f"{self.prefix} {original_message}"

def _create_logger(name, prefix):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = PrefixFormatter(
            prefix=prefix,
            fmt="%(levelname)s:%(name)s: %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def get_logger():
    return _create_logger("user", "[PUBLIC]")


def get_provider_logger():
    return _create_logger("provider", "[PRIVATE]")