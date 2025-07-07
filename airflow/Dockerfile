FROM apache/airflow:2.6.3

USER root
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
# Install classic Docker Compose (v1) CLI so BashOperator can invoke
# `docker-compose …` inside the Airflow container.  We install it later
# as *airflow* user to comply with the upstream image guidelines.

ARG GITHUB_TOKEN
RUN if [ -z "$GITHUB_TOKEN" ]; then \
      echo "GITHUB_TOKEN build arg is required" >&2; exit 1; \
    fi
RUN git clone https://${GITHUB_TOKEN}@github.com/jpl-labcas/publish.git /opt/publish

RUN if [ -f /opt/publish/setup.py ]; then \
      pip install /opt/publish; \
    elif [ -f /opt/publish/publish ]; then \
      chmod +x /opt/publish/publish && ln -s /opt/publish/publish /usr/local/bin/publish; \
    fi

COPY scripts/start_local_executor.sh /opt/airflow/scripts/start_local_executor.sh
RUN chmod +x /opt/airflow/scripts/start_local_executor.sh

USER airflow
# Add docker-compose together with the other Python dependencies
RUN pip install --no-cache-dir pandas openpyxl docker psycopg2-binary docker-compose
