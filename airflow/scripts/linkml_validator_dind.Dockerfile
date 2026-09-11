FROM python:3.10-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ARG LINKML_REPO_URL=https://github.com/usnistgov/nist-labcas-linkml.git
ARG LINKML_REPO_REF=main
ARG LINKML_GITHUB_TOKEN=
ARG LINKML_INSTALL_MODE=remote

RUN pip install --no-cache-dir "linkml-runtime>=1.9.4" "PyYAML>=6"
RUN if [ "${LINKML_INSTALL_MODE}" = "remote" ]; then \
      if [ -n "${LINKML_GITHUB_TOKEN}" ]; then \
        repo_url="${LINKML_REPO_URL#https://}"; \
        auth_url="https://x-access-token:${LINKML_GITHUB_TOKEN}@${repo_url}"; \
        git clone --depth 1 --branch "${LINKML_REPO_REF}" "${auth_url}" /opt/nist-labcas-linkml; \
      else \
        git clone --depth 1 --branch "${LINKML_REPO_REF}" "${LINKML_REPO_URL}" /opt/nist-labcas-linkml; \
      fi; \
      pip install --no-cache-dir /opt/nist-labcas-linkml; \
    elif [ "${LINKML_INSTALL_MODE}" = "local" ]; then \
      mkdir -p /opt/nist-labcas-linkml; \
    else \
      echo "Unknown LINKML_INSTALL_MODE=${LINKML_INSTALL_MODE}" >&2; exit 1; \
    fi

COPY linkml_validate.py /opt/linkml/linkml_validate.py
RUN chmod +x /opt/linkml/linkml_validate.py

ENV PYTHONPATH=/opt/nist-labcas-linkml/src
WORKDIR /opt/linkml
CMD ["sleep", "infinity"]
