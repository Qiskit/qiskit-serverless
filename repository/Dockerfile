FROM python:3.9.16-slim-buster

WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

USER 0
RUN apt-get update && apt-get install -y vim
COPY repository .
RUN chown -R 1001:0 /usr/src/app &&\
    pip install -r requirements.txt --no-cache-dir

USER 1001

RUN sed -i 's/\r$//g' /usr/src/app/entrypoint.sh &&\
    chmod +x /usr/src/app/entrypoint.sh

EXPOSE 8060
# run entrypoint.sh
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
