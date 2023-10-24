#!/bin/bash

###NOTE
        ## Set up the environment variables needed for the curl command to run
        ## Ensure to add -k -v -x localhost:2222 at the end of each curl command for succesful execution
        ## Use "" <doble quotes for headers when you need to add a parameted
        ## Make sure the requried token is added to the travis integration or set up as an env variable that can be passed into the docker contaner for the sytem to use it

curl -s -X 'POST' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/signin' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'GET' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'GET' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/liveness' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'GET' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/readiness' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'GET' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1/jobs' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'GET' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1/jobs/:id' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'GET' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1/jobs/:id/logs' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'POST' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1/jobs/:id/result' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'POST' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1/jobs/:id/stop' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'GET' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1/programs' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'GET' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1/programs/:id' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'POST' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1/programs/upload' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'POST' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1/programs/run' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'POST' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1/programs/run_existing' \
        -H 'accept: application/json' -k -v -x localhost:2222

curl -s -X 'GET' \
        'https://gateway.middleware-nonprod-218f1d46487946bbe52597968f4638d3-0000.us-east.containers.appdomain.cloud/api/v1/files/download' \
        -H 'accept: application/json' -k -v -x localhost:2222
