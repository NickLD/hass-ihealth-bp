FROM python:3.14-slim
COPY requirements_test.txt /tmp/requirements_test.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r /tmp/requirements_test.txt
WORKDIR /src
