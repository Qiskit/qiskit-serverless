FROM registry.access.redhat.com/ubi9-minimal:9.4
RUN microdnf install -y python3.11-3.11.7 python3.11-pip-22.3.1 python3.11-devel-3.11.7 vim-enhanced-8.2.2637 &&\
    microdnf clean all
RUN ln -s /usr/bin/python3.11 /usr/local/bin/python3 && \
    ln -s /usr/bin/python3.11 /usr/local/bin/python &&\
    ln -s /usr/bin/pip3.11 /usr/local/bin/pip3 &&\
    ln -s /usr/bin/pip3.11 /usr/local/bin/pip

WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

USER 0
COPY gateway/requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir &&\
    cp -r -n /usr/local/lib64/python3.11/site-packages/symengine /usr/local/lib/python3.11/site-packages &&\
    cp -r -n /usr/local/lib/python3.11/site-packages/symengine /usr/local/lib64/python3.11/site-packages
COPY gateway .
RUN chown -R 1000:100 /usr/src/app &&\
    mkdir /usr/src/app/media && chown 1000:100 /usr/src/app/media

USER 1000:100
RUN sed -i 's/\r$//g' /usr/src/app/entrypoint.sh &&\
    chmod +x /usr/src/app/entrypoint.sh

EXPOSE 8000
# run entrypoint.sh
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
