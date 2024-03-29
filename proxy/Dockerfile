FROM python:3.9.16-slim-buster

WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

USER 0:123

RUN apt-get -y update && apt-get install  --no-install-recommends -y iptables=1.8.2-4 &&\
    apt-get clean &&\
    rm -rf /var/lib/apt/lists/*

RUN pip install headerparser==0.5.1 certifi==2024.2.2 requests==2.31.0
COPY proxy/proxy .
RUN chown -R 0:123 /usr/src/app

USER 0:123
RUN chmod +x /usr/src/app/entrypoint.sh

EXPOSE 8443
# run entrypoint.sh
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
