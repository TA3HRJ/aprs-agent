# APRS-Agent — Web GUI in a container
#
# Quick start:
#   docker build -t aprs-agent .
#   docker run -d --name aprs-agent \
#     -p 127.0.0.1:8080:8080 -p 8082:8082 \
#     -v "$(pwd)/data:/data" aprs-agent
#
# First run writes a default config to ./data/aprsconfig.toml — edit it (or
# use the Web GUI at http://localhost:8080) and set your callsign. The
# station database persists in the same volume.
#
# SECURITY: the admin panel on 8080 has no authentication of its own.
# Publish it to 127.0.0.1 only (as above) or put it behind a reverse proxy
# with auth. Port 8082 is the read-only public page — safe to expose once
# enabled via public_port in the config.

FROM python:3.11-slim

WORKDIR /app

# Dependency layer first, so code changes don't re-install everything
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Config + SQLite station DB live here — mount it to keep them
VOLUME /data

EXPOSE 8080 8082

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
  CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8080/api/status',timeout=5)" || exit 1

CMD ["python", "web_gui.py", "-c", "/data/aprsconfig.toml", \
     "--host", "0.0.0.0", "-p", "8080", "--no-browser"]
