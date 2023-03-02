from keycloak import KeycloakOpenID
from keycloak.exceptions import KeycloakInvalidTokenError
from django.http.response import JsonResponse
from rest_framework.exceptions import PermissionDenied, AuthenticationFailed, NotAuthenticated
import os

class KeycloakMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        KEYCLOAK_SERVER_URL=os.getenv('KEYCLOAK_SERVER_URL')
        CLIENT_SECRET=os.getenv('CLIENT_SECRET')
        KEYCLOAK_PUBLIC_KEY=os.getenv('KEYCLOAK_PUBLIC_KEY')

        self.OIDC=KeycloakOpenID(server_url=KEYCLOAK_SERVER_URL,
                       client_id="quantumrepository",
                       realm_name="quantumserverless",
                       client_secret_key=CLIENT_SECRET)        
        self.publickey='-----BEGIN PUBLIC KEY-----'+"\n"+KEYCLOAK_PUBLIC_KEY+"\n"+'-----END PUBLIC KEY-----'

    def __call__(self, request):
        if 'HTTP_AUTHORIZATION' not in request.META:
            return JsonResponse({"detail": NotAuthenticated.default_detail},
                                status=NotAuthenticated.status_code)
        auth_header = request.META.get('HTTP_AUTHORIZATION').split()
        token = auth_header[1] if len(auth_header) == 2 else auth_header[0]
        print(self.publickey)
        try:
            options = {"verify_signature": True, "verify_aud": False, "verify_exp": True}
            token_dict=self.OIDC.decode_token(token, key=self.publickey, options=options)
            #print(token_dict)
            username=token_dict['preferred_username']
            request.user=username 
            #print(request.user)
            
        except KeycloakInvalidTokenError as e:
            print(e)
            return JsonResponse({"detail": AuthenticationFailed.default_detail},
                                status=AuthenticationFailed.status_code)
        response = self.get_response(request)
        return response
