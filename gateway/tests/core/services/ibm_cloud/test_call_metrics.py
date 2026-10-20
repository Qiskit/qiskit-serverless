"""Tests for the Code Engine and COS call samples reported through call_metrics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from ibm_botocore.awsrequest import AWSResponse
from ibm_botocore.exceptions import ClientError
from urllib3 import HTTPResponse
from urllib3.exceptions import ProtocolError

from core.ibm_cloud import call_metrics, get_ce_auth
from core.ibm_cloud.clients import IBMCloudClientProvider
from core.ibm_cloud.code_engine.ce_client import FleetsApi
from core.ibm_cloud.code_engine.ce_client.rest import ApiException

LIST_FLEETS = "GET /projects/{project_id}/fleets"


@pytest.fixture
def recorder():
    recorder = MagicMock()
    call_metrics.set_recorder(recorder)
    yield recorder
    call_metrics.set_recorder(None)


def _fleets_api(status: int) -> FleetsApi:
    with patch("core.ibm_cloud.clients.get_iam_token_provider"):
        api_client = get_ce_auth("dummy-key", "us-east").api_client
    api_client.rest_client.pool_manager = MagicMock()
    api_client.rest_client.pool_manager.request.return_value = HTTPResponse(
        body=b'{"fleets": [], "limit": 100}', status=status, headers={}
    )
    return FleetsApi(api_client)


def _cos_client():
    with patch("core.ibm_cloud.clients.get_iam_token_provider"):
        provider = IBMCloudClientProvider(api_key="dummy-key", region="us-east")
    return provider.get_cos_hmac_client(access_key_id="ak", secret_access_key="sk")


def test_a_code_engine_429_is_recorded_and_still_raises(recorder):
    with pytest.raises(ApiException):
        _fleets_api(429).list_fleets("p1")

    endpoint, status, seconds = recorder.observe_code_engine_call.call_args.args
    assert (endpoint, status) == (LIST_FLEETS, "429")
    assert seconds >= 0


def test_a_code_engine_success_is_recorded_as_ok(recorder):
    _fleets_api(200).list_fleets("p1")

    assert recorder.observe_code_engine_call.call_args.args[:2] == (LIST_FLEETS, "ok")


def test_a_cos_call_is_recorded_with_its_operation_and_status(recorder):
    s3 = _cos_client()
    answers = iter([(200, b""), (403, b"<Error><Code>AccessDenied</Code></Error>")])

    def send(request, **_):
        status, body = next(answers)
        return AWSResponse(request.url, status, {}, MagicMock(stream=lambda: iter([body])))

    s3.meta.events.register("before-send.s3", send)
    s3.put_object(Bucket="b", Key="k", Body=b"x")
    with pytest.raises(ClientError):
        s3.list_objects_v2(Bucket="b")

    calls = [c.args[:2] for c in recorder.observe_cos_call.call_args_list]
    assert calls == [("PutObject", "200"), ("ListObjectsV2", "403")]


def test_a_cos_call_with_no_answer_is_recorded_as_0(recorder):
    s3 = _cos_client()

    def send(**_):
        raise ValueError("no answer")

    s3.meta.events.register("before-send.s3", send)
    with pytest.raises(ValueError):
        s3.head_object(Bucket="b", Key="k")

    assert recorder.observe_cos_call.call_args.args[:2] == ("HeadObject", "0")


def test_a_code_engine_connection_error_is_recorded_with_its_class(recorder):
    api = _fleets_api(200)
    api.api_client.rest_client.pool_manager.request.side_effect = ProtocolError("reset")

    with pytest.raises(ProtocolError):
        api.list_fleets("p1")

    assert recorder.observe_code_engine_call.call_args.args[:2] == (
        LIST_FLEETS,
        "ProtocolError",
    )
