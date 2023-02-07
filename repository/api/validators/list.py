from rest_framework import serializers
from typing import Any, Dict, List, OrderedDict, Union


class List:
    """
    TODO: description
    """

    def __init__(self, fields: List[str], nullable=True):
        self.fields = fields
        self.nullable = nullable

    def __call__(self, attrs: OrderedDict[str, Any]):
        error_messages = {}

        for field in self.fields:
            error_message = self.validate(field, attrs[field])
            if error_message is not None:
                error_messages.update(error_message)

        if error_messages:
            raise serializers.ValidationError(error_messages)

    def validate(self, field: str, value: Any) -> Union[Dict[str, str], None]:
        if value is None:
            if not self.nullable:
                return {f"{field}": "This field may not be null."}
        else:
            # Using `type` instead of `isinstance` to validate that it is a list and no a subtype
            value_type = type(value)
            if value_type is not list:
                return {f"{field}": "This field must be a valid list."}
        return None
