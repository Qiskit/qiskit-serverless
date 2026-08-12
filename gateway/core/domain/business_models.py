"""Business model constants shared across core and domain layers."""


class BusinessModel:  # pylint: disable=too-few-public-methods
    """Constants for the business model types of provider functions."""

    TRIAL = "TRIAL"
    SUBSIDIZED = "SUBSIDIZED"
    CONSUMPTION = "CONSUMPTION"


# Business model names as the billing service expects them. Subsidized functions
# are billed as licensed; the rest keep their own name, lowercased. Every
# BusinessModel constant must appear here.
BILLING_NAMES = {
    BusinessModel.SUBSIDIZED: "licensed",
    BusinessModel.TRIAL: "trial",
    BusinessModel.CONSUMPTION: "consumption",
}


def billing_name_for(business_model: str) -> str:
    """
    Return the billing name for a business model.

    Raises ValueError if the business model has no billing name, so a newly
    added model cannot be silently billed under a guessed name.
    """
    try:
        return BILLING_NAMES[business_model]
    except KeyError:
        raise ValueError(f"No billing name mapped for business model: {business_model!r}") from None
