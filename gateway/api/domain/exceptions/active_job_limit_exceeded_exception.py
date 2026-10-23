"""The user already has as many active jobs as they are allowed."""


class ActiveJobLimitExceeded(Exception):
    """The submit is refused because the user is at gateway.limits.active_jobs_per_user."""

    def __init__(self, limit: int):
        self.limit = limit
        self.message = f"Active job limit reached. The maximum allowed is {self.limit}."
        super().__init__(self.message)
