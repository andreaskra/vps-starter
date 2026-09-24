FROM python:3.12-slim

# docker CLI (static binary) — used to run certbot as a sibling container
# and to reload nginx. Talks to the host daemon via the mounted socket.
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

ENV DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
