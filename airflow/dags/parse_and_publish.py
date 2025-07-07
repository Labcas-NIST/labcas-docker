from datetime import datetime
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount
import os
import logging

# Host path for the data directory. Defaults to '/data' if the environment
# variable is not set. This allows running the DAG without creating a global
# '/data' directory on the host by specifying HOST_DATA_PATH=<project>/data
# when starting Airflow.

with DAG(
    dag_id="parse_and_publish",
    start_date=datetime(2023, 1, 1),
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
) as dag:

    parse_task = BashOperator(
        task_id="parse_excel",
        bash_command="set -euxo pipefail; ls -al /data; python /opt/airflow/scripts/parse_excel.py /data/input.xlsx /data/output.json; cat /data/output.json",
    )

    # Resolve host paths identical to docker-compose *publish* service.
    # Ensure the result is an *absolute* host path because Docker bind mounts
    # refuse to accept relative sources.
    host_data_env = os.getenv("HOST_DATA_PATH", "")
    if host_data_env:
        host_data = host_data_env if os.path.isabs(host_data_env) else os.path.abspath(host_data_env)
    else:
        host_data = os.path.abspath("./data")
    # Determine metadata host path:
    # 1. If HOST_METADATA_PATH is supplied *and* absolute, trust it verbatim.
    # 2. Otherwise derive it as a sibling of HOST_DATA_PATH so the resulting
    #    path is guaranteed to exist on the host filesystem (Docker bind
    #    requirement).  As a final fallback use the project-local ./metadata.
    metadata_env = os.getenv("HOST_METADATA_PATH", "")
    if metadata_env and os.path.isabs(metadata_env):
        metadata_host = metadata_env
    else:
        # Always derive metadata as a sibling of HOST_DATA_PATH; Docker only
        # needs the directory to exist. Skip creating it here to avoid
        # permission errors inside the Airflow container; the directory should
        # already exist on the *host* before the DAG runs.
        metadata_host = os.path.abspath("/metadata")
    labcas_data_host = os.path.abspath("./data/labcas-data")
    archive_host = os.path.abspath("./data/archive")
    publish_config_host = os.path.abspath("./shared-config/publish")

    basic_auth_user = os.getenv("BASIC_AUTH_USER", "dliu")
    basic_auth_pass = os.getenv("BASIC_AUTH_PASS", "secret")
 
    # ------------------------------------------------------------------
    # Publish task: invoke the existing docker-compose “publish” service
    # ------------------------------------------------------------------
    #
    # Instead of spinning a fresh container with DockerOperator, leverage the
    # service already defined in docker-compose.yml so it inherits exactly the
    # same mounts (metadata, data, archive, etc.) proven to work.
    #
    # `docker-compose run --rm publish` starts a one-off container from that
    # service definition and removes it when done.  The image’s default CMD
    # already runs the publishing pipeline so the bash command is empty.
    #
    # docker-compose gets installed into ~/.local/bin inside the Airflow image,
    # which is not on PATH when Airflow executes bash commands.  Prefix PATH
    # so the binary is discoverable.
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
            "-e PUBLISH_STEPS=\"$PUBLISH_STEPS\" "
            "-e steps=\"$PUBLISH_STEPS\" "
            "-e PUBLISH_CONSORTIUM=\"$PUBLISH_CONSORTIUM\" "
            "-e PUBLISH_COLLECTION=\"$PUBLISH_COLLECTION\" "
            "-e PUBLISH_COLLECTION_SUBSET=\"$PUBLISH_COLLECTION_SUBSET\" "
            "-e PUBLISH_ID=\"$PUBLISH_ID\" "
            "-e BASIC_AUTH_USER=\"$BASIC_AUTH_USER\" "
            "-e BASIC_AUTH_PASS=\"$BASIC_AUTH_PASS\" "
            "labcas-publish "
            "python3 /opt/publish/publishing_pipeline.py"
        ),
        env={
            "PUBLISH_STEPS": os.getenv("PUBLISH_STEPS", "crawl,publish"),
            # also expose the same value under key 'steps' because the publish image
            # expects that environment variable name
            "steps": os.getenv("PUBLISH_STEPS", "crawl,publish"),
            "PUBLISH_CONSORTIUM": os.getenv("PUBLISH_CONSORTIUM", "EDRN"),
            "PUBLISH_COLLECTION": os.getenv("PUBLISH_COLLECTION", "Basophile"),
            "PUBLISH_COLLECTION_SUBSET": os.getenv("PUBLISH_COLLECTION_SUBSET", ""),
            "PUBLISH_ID": os.getenv("PUBLISH_ID", ""),
            "BASIC_AUTH_USER": basic_auth_user,
            "BASIC_AUTH_PASS": basic_auth_pass,
        },
    )

    parse_task >> wait_publish >> publish_task
