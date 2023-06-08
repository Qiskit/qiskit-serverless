Quantum serverless gateway
==========================

Gateway is a set of apis that are used as a backend for providers.

### Build image

```shell
docker build -t qiskit/quantum-serverless-gateway:<VERSION> .
```

### Env variables for container

| Variable                               | Description                                                                                                                                                           |
|----------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| DEBUG                                  | run application on debug mode                                                                                                                                         |
| SITE_HOST                              | host of site that will be created for Django application                                                                                                              |
| RAY_HOST                               | Host of Ray head node that will be assigned to default created compute resource                                                                                       |
| CLIENT_ID                              | Keycloak client id that will be created for social integrations                                                                                                       |
| DJANGO_SUPERUSER_USERNAME              | username for admin user that is created on launch of container                                                                                                        |
| DJANGO_SUPERUSER_PASSWORD              | password for admin user that is created on launch of container                                                                                                        |
| DJANGO_SUPERUSER_EMAIL                 | email for admin user that is created on launch of container                                                                                                           |
| SETTING_KEYCLOAK_URL                   | url to keycloak instance                                                                                                                                              |
| SETTING_KEYCLOAK_REALM                 | Realm of keycloak to authenticate with                                                                                                                                |
| SETTINGS_KEYCLOAK_CLIENT_SECRET        | client secret                                                                                                                                                         |
| SETTINGS_TOKEN_AUTH_URL                | URL for custom token authentication                                                                                                                                   |
| SETTINGS_TOKEN_AUTH_USER_FIELD         | user field name for custom token authentication mechanism. Default `userId`.                                                                                          |
| SETTINGS_TOKEN_AUTH_TOKEN_FIELD        | user field name for custom token authentication mechanism. Default `apiToken`.                                                                                        |
| SETTINGS_AUTH_MECHANISM                | authentication backend mechanism. Default `default`. Options: `default` and `custom_token`. If `custom_token` is selected then `SETTINGS_TOKEN_AUTH_URL` must be set. |
| SETTINGS_TOKEN_AUTH_VERIFICATION_URL   | URL for custom token verificaiton                                                                                                                                     |
| SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD | name of a field to use for token verification                                                                                                                         | 
| RAY_KUBERAY_NAMESPACE                  | namespace of kuberay resources. Should match kubernetes namespace                                                                                                     |
| RAY_NODE_IMAGE                         | Default node image that will be launched on ray cluster creation                                                                                                      |
| RAY_CLUSTER_MODE_LOCAL                 | 0 or 1. 1 for local mode (docker-compose), 0 for cluster mode where clusters will be created by kuberay                                                               |
| RAY_CLUSTER_MODE_LOCAL_HOST            | if `RAY_CLUSTER_MODE_LOCAL` set to 1, then this host for ray head node will be used to run all workloads                                                              |
| LIMITS_JOBS_PER_USER                   | number of concurrent programs/jobs user can run at single point of time                                                                                               |
| LIMITS_MAX_CLUSTERS                    | number of compute resources can be allocated in single point of time                                                                                                  | 
| RAY_CLUSTER_TEMPLATE_CPU               | default compute kuberay template cpu setting                                                                                                                          |
| RAY_CLUSTER_TEMPLATE_MEM               | default compute kuberay template memory setting                                                                                                                       |
| RAY_CLUSTER_WORKER_REPLICAS            | worker replicas per cluster                                                                                                                                           |
| RAY_CLUSTER_WORKER_MIN_REPLICAS        | min worker replicas per cluster                                                                                                                                       |
| RAY_CLUSTER_WORKER_MAX_REPLICAS        | max replicas per cluster                                                                                                                                              |
