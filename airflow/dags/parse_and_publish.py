from datetime import datetime
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount
import os
import logging


with DAG(
    dag_id="parse_and_publish",
    start_date=datetime(2023, 1, 1),
    schedule_interval='@once',
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
) as dag:

    parse_task = BashOperator(
        task_id="parse_excel",
        bash_command="set -euxo pipefail; ls -al /data; python /opt/airflow/scripts/parse_excel.py /data/raw/Basophile.csv /data/staging/Basophile/Basophile.cfg",
    )
    
    basic_auth_user = os.getenv("BASIC_AUTH_USER", "")
    basic_auth_pass = os.getenv("BASIC_AUTH_PASS", "")

 
    # ------------------------------------------------------------------
    # Publish task: exec the running labcas-publish container (DIND)
    # ------------------------------------------------------------------
    #
    # The Airflow entrypoint starts a long-running labcas-publish container
    # inside the DIND daemon with the same mounts as the publish service.
    # We wait for it, then exec the pipeline with run-specific env vars.
    # ------------------------------------------------------------------
    # Sensor: wait until the long-running labcas-publish container is up
    # ------------------------------------------------------------------
    wait_publish = BashOperator(
        task_id="wait_publish_container",
        bash_command=(
            "{% raw %}"
            "set -euo pipefail; "
            # Exit 0 only when container exists and is running
            "while true; do "
            "  status=$(docker inspect -f '{{.State.Running}}' labcas-publish 2>/dev/null || echo 'false'); "
            "  if [ \"$status\" = \"true\" ]; then break; fi; "
            "  echo 'Waiting for labcas-publish container...'; "
            "  sleep 5; "
            "done"
            "{% endraw %}"
        ),
    )

    # ------------------------------------------------------------------
    # Publish task: exec the pipeline inside the running labcas-publish
    # ------------------------------------------------------------------
    publish_task = BashOperator(
        task_id="publish_metadata",
        bash_command=(
            "set -euo pipefail; "
            "docker exec "
            "-e steps=\"$PUBLISH_STEPS\" "
            "-e PUBLISH_CONSORTIUM=\"$PUBLISH_CONSORTIUM\" "
            "-e PUBLISH_COLLECTION=\"$PUBLISH_COLLECTION\" "
            "-e PUBLISH_COLLECTION_SUBSET=\"$PUBLISH_COLLECTION_SUBSET\" "
            "-e PUBLISH_ID=\"$PUBLISH_ID\" "
            "-e SOLR_URL=\"$SOLR_URL\" -e solr=\"$solr\" "
            "-e BASIC_AUTH_USER=\"$BASIC_AUTH_USER\" "
            "-e BASIC_AUTH_PASS=\"$BASIC_AUTH_PASS\" "
            "labcas-publish "
            "python3 /opt/publish/publishing_pipeline.py"
        ),
        env={
            "PUBLISH_STEPS": os.getenv("PUBLISH_STEPS", "crawl,publish"),
            "PUBLISH_CONSORTIUM": os.getenv("PUBLISH_CONSORTIUM", "NIST"),
            "PUBLISH_COLLECTION": os.getenv("PUBLISH_COLLECTION", "Basophile"),
            "PUBLISH_COLLECTION_SUBSET": os.getenv("PUBLISH_COLLECTION_SUBSET", ""),
            "PUBLISH_ID": os.getenv("PUBLISH_ID", ""),
            "SOLR_URL": os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/"),
            "solr": os.getenv("solr", os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/")),
            "BASIC_AUTH_USER": basic_auth_user,
            "BASIC_AUTH_PASS": basic_auth_pass,
        },
    )

    parse_task >> wait_publish >> publish_task
