"""
Dict validator to be used in the serializers.
"""

from typing import Any, Dict, List, OrderedDict, Union
from rest_framework import serializers


class DictValidator:
    """
    This validator checks if a specific set of fields contains:
        - A value of type `dict`
        - If the value can be `null` or not

    :param fields: set of fields that will be checked by this validator
    :param nullable: specifies if the validator may accept `null` values
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
        """
        Method that checks if the value of a specific field is a valid `dict`.

        :param field: name of the model attribute
        :param value: field content to be checked
        :return:
            an error message of type:
                `{ f"{field}": f"{error_message}" }`
            if the value is not valid
        """

        if value is None:
            if not self.nullable:
                return {f"{field}": "This field may not be null."}
        else:
            # Using `type` instead of `isinstance` to validate that it is a dict and no a subtype
            value_type = type(value)
            if value_type is not dict:
                return {f"{field}": "This field must be a valid dict."}
        return None
