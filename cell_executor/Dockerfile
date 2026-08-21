FROM python:3.12-alpine

WORKDIR /app
COPY cell_executor/main.py /app/main.py

RUN addgroup -S -g 65532 nonroot \
    && adduser -S -D -H -u 65532 -G nonroot nonroot \
    && chmod 0555 /app/main.py

USER 65532:65532
ENTRYPOINT ["python", "/app/main.py"]
