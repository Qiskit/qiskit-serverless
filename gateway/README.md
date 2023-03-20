Quantum serverless gateway
==========================

Gateway is a set of apis that are used as a backend for providers.

### Build image

```shell
docker build -t qiskit/quantum-serverless-gateway:<VERSION> .
```

### Env variables for container

| Variable                        | Description                                                                     |
|---------------------------------|---------------------------------------------------------------------------------|
| DEBUG                           | run application on debug mode                                                   |
| SITE_HOST                       | host of site that will be created for Django application                        |
| RAY_HOST                        | Host of Ray head node that will be assigned to default created compute resource |
| CLIENT_ID                       | Keycloak client id that will be created for social integrations                 |
| DJANGO_SUPERUSER_USERNAME       | username for admin user that is created on launch of container                  |
| DJANGO_SUPERUSER_PASSWORD       | password for admin user that is created on launch of container                  |
| DJANGO_SUPERUSER_EMAIL          | email for admin user that is created on launch of container                     |
| SETTING_KEYCLOAK_URL            | url to keycloak instance                                                        |
| SETTING_KEYCLOAK_REALM          | Realm of keycloak to authenticate with                                          |
| SETTINGS_KEYCLOAK_CLIENT_SECRET | client secret                                                                   | 
| SETTINGS_KEYCLOAK_CLIENT_NAME   | client name                                                                     |
