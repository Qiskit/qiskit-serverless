FROM python:3.9.16-slim-buster

WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

USER 0
RUN apt-get -y update
RUN apt-get install -y iptables
RUN apt-get install -y tcpdump
#COPY proxy/requirements.txt .
#RUN pip install -r requirements.txt --no-cache-dir
RUN pip install headerparser
COPY proxy .
RUN chown -R 0:112 /usr/src/app

USER 0:123
RUN chmod +x /usr/src/app/entrypoint.sh

EXPOSE 8443
# run entrypoint.sh
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
