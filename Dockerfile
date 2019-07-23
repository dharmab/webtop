FROM python:3.7-alpine
WORKDIR /webtop
ADD requirements.txt .
RUN pip install -r requirements.txt
ADD webtop .
ENTRYPOINT python webtop/__init__.py
