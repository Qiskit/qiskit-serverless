#!/usr/bin/python
# -*- coding: utf-8 -*-
from keycloak import KeycloakOpenID
from keycloak.exceptions import KeycloakInvalidTokenError
from django.http.response import JsonResponse
from rest_framework.exceptions import (
    PermissionDenied,
    AuthenticationFailed,
    NotAuthenticated,
)
import os


class KeycloakMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        KEYCLOAK_SERVER_URL = os.getenv("KEYCLOAK_SERVER_URL")
        CLIENT_SECRET = os.getenv("CLIENT_SECRET")
        KEYCLOAK_PUBLIC_KEY = os.getenv("KEYCLOAK_PUBLIC_KEY")

        self.OIDC = KeycloakOpenID(
            server_url=KEYCLOAK_SERVER_URL,
            client_id="quantumrepository",
            realm_name="quantumserverless",
            client_secret_key=CLIENT_SECRET,
        )
        if not KEYCLOAK_PUBLIC_KEY:
            keycloak_public_key = self.OIDC.public_key()
        else:
            keycloak_public_key = KEYCLOAK_PUBLIC_KEY
        self.publickey = (
            "-----BEGIN PUBLIC KEY-----"
            + "\n"
            + str(keycloak_public_key)
            + "\n"
            + "-----END PUBLIC KEY-----"
        )

    def __call__(self, request):
        if "HTTP_AUTHORIZATION" not in request.META:
            return JsonResponse(
                {"detail": NotAuthenticated.default_detail},
                status=NotAuthenticated.status_code,
            )
        auth_header = request.META.get("HTTP_AUTHORIZATION").split()
        token = auth_header[1] if len(auth_header) == 2 else auth_header[0]
        try:
            options = {
                "verify_signature": True,
                "verify_aud": False,
                "verify_exp": True,
            }
            token_dict = self.OIDC.decode_token(
                token, key=self.publickey, options=options
            )
            name = token_dict["preferred_username"]
            request.OIDC = name

        except KeycloakInvalidTokenError as e:
            request.OIDC = "none"
        response = self.get_response(request)
        return response
