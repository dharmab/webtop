FROM python:3.7-alpine
ADD requirements.txt .
RUN apk add build-base libressl libffi-dev && \
  pip install -r requirements.txt && \
  apk del build-base libffi-dev
ADD webtop .
ENTRYPOINT python webtop/__init__.py
