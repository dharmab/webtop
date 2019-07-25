FROM python:3.7-alpine
WORKDIR webtop
ADD requirements.txt .
RUN apk add build-base && \
  pip install -r requirements.txt && \
  apk del build-base
ADD webtop/__init__.py webtop.py
ENTRYPOINT ["python", "webtop.py"]
