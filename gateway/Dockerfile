FROM python:3.10.12-slim-buster

WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# install psycopg2 dependencies
RUN apt-get -y update &&\
    apt-get install --no-install-recommends -y gcc=4:8.3.0-1 python3-dev=3.7.3-1 vim=2:8.1.0875-5+deb10u6 &&\
    apt-get clean &&\
    rm -rf /var/lib/apt/lists/*

USER 0
COPY gateway/requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir
COPY gateway .
RUN chown -R 1000:100 /usr/src/app &&\
    mkdir /usr/src/app/media && chown 1000:100 /usr/src/app/media

USER 1000:100
RUN sed -i 's/\r$//g' /usr/src/app/entrypoint.sh &&\
    chmod +x /usr/src/app/entrypoint.sh

EXPOSE 8000
# run entrypoint.sh
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
