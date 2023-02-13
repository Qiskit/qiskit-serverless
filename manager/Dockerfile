FROM python:3.8-slim-buster

WORKDIR /python-docker

COPY manager/requirements.txt requirements.txt

RUN pip --trusted-host files.pythonhosted.org --trusted-host pypi.org --trusted-host pypi.python.org install -r requirements.txt
# Install kubectl from Docker Hub.
COPY --from=lachlanevenson/k8s-kubectl:v1.25.4 /usr/local/bin/kubectl /usr/local/bin/kubectl
# Install helm
#RUN apk upgrade && apk add curl openssl bash --no-cache
RUN apt-get update; apt-get install -y curl
RUN curl -LO "https://storage.googleapis.com/kubernetes-release/release/$(curl -s https://storage.googleapis.com/kubernetes-release/release/stable.txt)/bin/linux/amd64/kubectl" \
    && chmod +x ./kubectl \
    && mv ./kubectl /usr/local/bin/kubectl \
    && curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 \
    && chmod +x get_helm.sh && ./get_helm.sh

COPY manager/manager/* manager/

ENV FLASK_APP manager/app.py

CMD [ "python3", "-m" , "flask", "run", "--host=0.0.0.0", "--port=5000"]