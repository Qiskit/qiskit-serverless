from rest_framework import serializers
from typing import List


class List:
    """
    TODO: description
    """

    def __init__(self, fields: List[str], nullable=True):
        self.fields = fields
        self.nullable = nullable

    def __call__(self, attrs):
        for field in self.fields:
            self.validate(field, attrs[field])

    def validate(self, field, value):
        if value is None:
            if self.nullable is False:
                raise serializers.ValidationError({f"{field}": "This field may not be null."})
        else:
            # Using `type` instead of `isinstance` to validate that it is a list and no a subtype
            value_type = type(value)
            if value_type is not list:
                raise serializers.ValidationError({f"{field}": "This field must be a valid list."})
