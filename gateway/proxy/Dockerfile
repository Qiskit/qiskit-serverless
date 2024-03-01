FROM python:3.9.16-slim-buster

WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

USER 0:123
RUN apt-get -y update
RUN apt-get install -y iptables
RUN apt-get install -y tcpdump
RUN pip install headerparser
RUN pip install certifi
RUN pip install requests
COPY proxy .
RUN chown -R 0:123 /usr/src/app

USER 0:123
RUN chmod +x /usr/src/app/entrypoint.sh

EXPOSE 8443
# run entrypoint.sh
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
