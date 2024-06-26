FROM python:3.11-alpine3.20

COPY requirements.txt .
COPY dist/trixelmanagementserver* ./dist/
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --force-reinstall dist/*.whl

# Add adapter requirements for postgres/timescaledb
RUN apk update \
    && apk add --virtual build-deps gcc libpq-dev python3-dev musl-dev\
    && apk add --no-cache libpq-dev
RUN pip install --no-cache-dir cryptography psycopg2
RUN apk del build-deps

EXPOSE 80

CMD ["uvicorn", "trixelmanagementserver:app", "--host", "0.0.0.0", "--port", "80"]