"""
This class defines TypeFilter enum for views:
"""

from enum import Enum


class TypeFilter(str, Enum):
    """
    TypeFilter values for the view end-points:
    - SERVERLESS
    - CATALOG
    """

    SERVERLESS = "serverless"
    CATALOG = "catalog"
