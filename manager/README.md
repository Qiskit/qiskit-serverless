Ray cluster manager middleware
==============================

Ray cluster manager middleware is the API which permits the management of ray clusters at a high level.


## Development

**Setup environment**

`conda create -n quantum_serverless_middleware python=3.9
`

`conda activate quantum_serverless_middleware
`

`pip install -r requirements.txt
`

**Setup the application** 

`export FLASK_APP=manager/app.py
`

`export FLASK_ENV=development
`
`export NAMESPACE=ray`

`cp -R ../infrastructure/ray .`

`flask run`

**Build docker application**

Point the shell to minikube's docker-daemon:

`eval $(minikube -p minikube docker-env)`

Build container (from root directory):


`docker build -f manager/Dockerfile -t manager:0.0.1 .`


`kubectl -n ray run manager --env="NAMESPACE=ray" --image=manager:0.0.1`



`kubectl apply -f pod.yaml`

`kubectl apply -f role.yaml`

`kubectl apply -f role-binding.yaml`

`kubectl apply -f cluster-role.yaml`

`kubectl apply -f cluster-role-binding.yaml`


`kubectl -n ray port-forward manager 5002:5000`

`kubectl -n ray exec --stdin --tty manager -- /bin/bash`