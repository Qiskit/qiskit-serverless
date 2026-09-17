"""
Temporary translation of the old SUBSIDIZED business model into its new name, LICENSED.

Everything about the old name lives in this one file so that removing it later is a single
delete: once a data migration rewrites the SUBSIDIZED rows of api_job, this file and every
one of its usages go away.
"""

from core.domain.business_models import BusinessModel


def licensed_instead_of_subsidized(business_model: str) -> str:
    """Return LICENSED when given the old name of that same business model."""
    if business_model == BusinessModel.SUBSIDIZED:
        return BusinessModel.LICENSED
    return business_model


def licensed_job_from_db(job, field_names):
    """Replace the old business model name on a job row just read from the database.

    Called from Job.from_db, so no code above the model ever sees the old name: not the
    serializers, not the admin, not the billing events. field_names is checked because a
    deferred query (only/defer/refresh_from_db) may not have loaded the field at all.
    """
    if "business_model" in field_names:
        job.business_model = licensed_instead_of_subsidized(job.business_model)
    return job
