FROM apache/airflow:2.6.3

USER root
RUN apt-get update && apt-get install -y git docker.io iptables && rm -rf /var/lib/apt/lists/*
# Install classic Docker Compose (v1) CLI so BashOperator can invoke
# `docker-compose …` inside the Airflow container.  We install it later
# as *airflow* user to comply with the upstream image guidelines.

ARG GITHUB_TOKEN
ARG PUBLISH_REPO_URL=https://github.com/jpl-labcas/publish.git
ARG PUBLISH_REPO_REF=simplified_publish
RUN if [ -z "$GITHUB_TOKEN" ]; then \
      echo "GITHUB_TOKEN build arg is required" >&2; exit 1; \
    fi
RUN git clone --branch "${PUBLISH_REPO_REF}" --single-branch "https://${GITHUB_TOKEN}@${PUBLISH_REPO_URL#https://}" /opt/publish

RUN if [ -f /opt/publish/setup.py ]; then \
      pip install /opt/publish; \
    elif [ -f /opt/publish/publish ]; then \
      chmod +x /opt/publish/publish && ln -s /opt/publish/publish /usr/local/bin/publish; \
    fi

COPY scripts/start_local_executor.sh /opt/airflow/scripts/start_local_executor.sh
RUN chmod +x /opt/airflow/scripts/start_local_executor.sh

USER airflow
# Add Python dependencies; avoid docker-compose to keep Airflow's deps intact.
RUN pip install --no-cache-dir pandas openpyxl docker psycopg2-binary
