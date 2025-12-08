# LabCAS Docker Dependencies and Compose Overview

This document summarizes the package dependencies for each container image defined in this repository and provides an overview of the overall `docker-compose` setup.

## Services Overview (docker-compose.yml)

- `ldap`: build `./ldap` (base: `bitnamilegacy/openldap:latest`)
- `labcas-backend`: build `./labcas-backend` (base: `openjdk:8-jdk`)
- `labcas-ui`: build `./labcas-ui` (base: `edrndocker/labcas-ubuntubase`)
- `mock-auth`: build `./mock-auth` (base: `node:16-alpine`)
- `labcas-proxy`: build `./labcas-proxy` (base: `edrndocker/labcas-ubuntubase`)
- `postgres`: image `postgres:13`
- `airflow`: build `./airflow` (base: `apache/airflow:2.6.3`)
- `publish`: build `./publish` (base: `python:3.10-slim`)
- `ldap-logs`: image `cr.fluentbit.io/fluent/fluent-bit:2.2`

Shared network: `labcas-net`

Named volumes: `labcas-solr-index`, `postgres-data`

## Per-Container Dependencies

### ldap (./ldap/Dockerfile)
- Base image: `bitnamilegacy/openldap:latest`
- OS/tools used: `openssl` (provided by base image)
- Actions: Generates self-signed certs and keys; adjusts permissions for slapd user.
- Additional: Copies initialization scripts from `./ldap` into the image.

### labcas-backend (./labcas-backend/Dockerfile) - (due to deprecation openJDK will be updated to later version)
- Base image: `openjdk:8-jdk`
- APT packages installed:
  - `wget`, `netcat-openbsd`, `git`, `vim`, `ldap-utils`, `maven`
- Build steps:
  - Clones `https://github.com/EDRN/labcas-backend.git`
  - Runs `mvn clean install` (pulls Java/Maven dependencies defined upstream)
- Other tools/config:
  - Uses `keytool` to create keystores/certs; prepares `start.sh`, `init_solr.sh`, and entrypoint.

### labcas-ui (./labcas-ui/Dockerfile)
- Base image: `edrndocker/labcas-ubuntubase`
- APT packages installed:
  - `apache2`, `apache2-utils`, `vim`, `git`
- App source:
  - Clones `https://github.com/Labcas-NIST/Labcas-ui.git` to `/var/www/html/labcas-ui`
- Web server:
  - Apache configuration files copied from this repo; exposes port `8081`.

### mock-auth (./mock-auth/Dockerfile)
- Base image: `node:16-alpine`
- NPM dependencies (from `./mock-auth/package.json`):
  - `express` `^4.21.2`
- Install command: `npm install --only=production`
- Entrypoint: `node mockAuth.js` on port `3001`.

### labcas-proxy (./labcas-proxy/Dockerfile)
- Base image: `edrndocker/labcas-ubuntubase` (provides nginx in this environment)
- APT packages installed:
  - `iputils-ping`, `net-tools`, `bind9-host`, `cron`, `logrotate`
- Web proxy:
  - Configures nginx site, TLS certs/keys; sets custom entrypoint.

### postgres (docker-compose image)
- Image: `postgres:13`
- Dependencies: standard Postgres distribution; configured via env vars and a named volume `postgres-data`.

### airflow (./airflow/Dockerfile)
- Base image: `apache/airflow:2.6.3`
- APT packages installed: `git`
- Python packages installed via pip:
  - `pandas`, `openpyxl`, `docker`, `psycopg2-binary`, `docker-compose`
- App/tools:
  - Clones `https://github.com/jpl-labcas/publish.git` into `/opt/publish` and installs it if `setup.py` or `publish` script is present.
  - Custom start script `scripts/start_local_executor.sh`.

### publish (./publish/Dockerfile)
- Base image: `python:3.10-slim`
- APT packages installed:
  - `git`, `gcc`, `libglib2.0-dev`, `libxml2-dev`, `libxslt1-dev`, `libjpeg-dev`, `zlib1g-dev`, `libopenjp2-7-dev`, `libtiff-dev`, `ca-certificates`
- Python dependencies:
  - Installs the `publish` project from `https://github.com/jpl-labcas/publish.git` via `setup.py` or `requirements.txt` in that repo (exact packages are defined upstream).
- Certificates/config:
  - Adds `labcas-ssl-cert.pem` to system CAs.
  - Sets `PYTHONPATH=/opt/publish/src`.

### ldap-logs (docker-compose image)
- Image: `cr.fluentbit.io/fluent/fluent-bit:2.2`
- Purpose: Collect and ship logs from Docker containers and LDAP logs using mounted configuration (`fluent-bit.conf`).

## docker-compose Configuration Summary

### Networks
- `labcas-net`: all services join this network.

### Named Volumes
- `labcas-solr-index`: used by `labcas-backend` for Solr index data.
- `postgres-data`: used by `postgres` for database storage.

### Service Ports and Mounts (key items)
- `ldap`: ports `1636:1636`; mounts `./ldap/custom_ldifs`, `./data/logs/ldap`.
- `labcas-backend`: ports `8444:8444`, `8984:8984`; mounts configs and logs; exposes `8081`, `8444`, `8984`.
- `labcas-ui`: port `8081:8081`; mounts environment config and logs.
- `mock-auth`: port `3001:3001`.
- `labcas-proxy`: ports `80:80`, `443:443`, `8099:8099`; mounts nginx logs.
- `postgres`: internal only; persists `postgres-data`.
- `airflow`: port `8082:8080`; mounts project DAGs, scripts, logs, data, metadata, docker socket, and compose file.
- `publish`: no published ports; mounts metadata, data, archive, labcas-data, publish config; healthcheck configured.
- `ldap-logs`: no published ports; mounts docker container logs, LDAP logs, and fluent-bit config.

### Environment Variables (selected)
- `ldap`: TLS enablement and cert paths; `LDAP_ROOT`, `LDAP_ADMIN_*`, logging.
- `labcas-backend`: `LABCAS_HOME=/tmp/labcas`.
- `postgres`: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`.
- `airflow`: executor and DB connection env; host path passthroughs for data and configs.
- `publish`: `SOLR_URL`/`solr`, `PUBLISH_CONSORTIUM`, `PUBLISH_COLLECTION`, `PUBLISH_STEPS`, etc.

### docker-compose.override.yml
- Adds shared configuration mounts under `./shared-config/*` for:
  - `labcas-backend` → `/config`
  - `labcas-ui` → `/config/labcas-ui`
  - `ldap` → `/config/ldap`
  - `publish` → `/config/publish`
  - `airflow` → `/config/airflow`

## Notes
- Several images clone and/or install from external GitHub repositories during build (`labcas-backend`, `airflow`, `publish`, `labcas-ui`). Upstream application/library dependencies are defined in those repositories and are not duplicated here.
