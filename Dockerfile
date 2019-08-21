FROM python:3.7-alpine
ADD requirements.txt .
RUN apk add --virtual .build-dependencies build-base libressl libffi-dev && \
  pip install -r requirements.txt && \
  apk del .build-dependencies
ADD webtop .
ENTRYPOINT python webtop/cli.py
