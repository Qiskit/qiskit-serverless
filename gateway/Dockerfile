FROM registry.access.redhat.com/ubi9/python-311

WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

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
