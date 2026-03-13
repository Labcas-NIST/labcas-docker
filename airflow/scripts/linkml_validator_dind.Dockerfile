FROM python:3.10-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ARG LINKML_REPO_URL=https://github.com/usnistgov/nist-labcas-linkml.git
ARG LINKML_REPO_REF=main
ARG LINKML_GITHUB_TOKEN=

RUN if [ -n "${LINKML_GITHUB_TOKEN}" ]; then \
      auth_url="$(echo "${LINKML_REPO_URL}" | sed "s#https://#https://${LINKML_GITHUB_TOKEN}@#")"; \
      git clone --depth 1 --branch "${LINKML_REPO_REF}" "${auth_url}" /opt/nist-labcas-linkml; \
    else \
      git clone --depth 1 --branch "${LINKML_REPO_REF}" "${LINKML_REPO_URL}" /opt/nist-labcas-linkml; \
    fi
RUN pip install --no-cache-dir /opt/nist-labcas-linkml

COPY linkml_validate.py /opt/linkml/linkml_validate.py
RUN chmod +x /opt/linkml/linkml_validate.py

WORKDIR /opt/linkml
CMD ["sleep", "infinity"]
