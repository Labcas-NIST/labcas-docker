from datetime import datetime
from airflow import DAG
from airflow.operators.bash import BashOperator
import os


with DAG(
    dag_id="microbial_strain_parse_and_publish",
    start_date=datetime(2023, 1, 1),
    schedule_interval="@once",
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
) as dag:

    # Optional cleanup to avoid stale artifacts; enable via RESET_BEFORE_RUN=true
    reset_task = BashOperator(
        task_id="reset_generated_state",
        bash_command=(
            "set -euo pipefail; "
            "if [ \"${RESET_BEFORE_RUN:-false}\" != \"true\" ]; then echo 'Reset disabled'; exit 0; fi; "
            "rm -rf /metadata/microbial_strain || true; "
            "rm -rf /data/archive/nist/microbial_strain || true; "
            "rm -rf /data/generated_metadata/nist/microbial_strain || true; "
            "echo 'Reset complete'"
        ),
    )

    # Parse CoreNMSC metadata and write cfgs under /metadata
    parse_task = BashOperator(
        task_id="parse_microbial_strain",
        bash_command=(
            "set -euxo pipefail; "
            "ls -al /data/raw || true; mkdir -p /metadata; "
            "mkdir -p \"/data/archive/nist/microbial_strain/strain\"; "
            "python /opt/airflow/scripts/parsers/microbe.py "
            "--input-file \"/data/raw/CoreNMSC V 1.0.csv\" "
            "--output-dir /metadata "
            "--collection microbial_strain "
            "--dataset strain "
            "--file-name \"MALDI V 1.0.csv\"; "
            "cp -f \"/data/raw/MALDI V 1.0.csv\" "
            "\"/data/archive/nist/microbial_strain/strain/MALDI V 1.0.csv\""
        ),
    )

    basic_auth_user = os.getenv("BASIC_AUTH_USER", "dliu")
    basic_auth_pass = os.getenv("BASIC_AUTH_PASS", "secret")

    # Wait for the long-running labcas-publish container to be healthy
    wait_publish = BashOperator(
        task_id="wait_publish_container",
        bash_command=(
            "{% raw %}"
            "set -euo pipefail; "
            "while true; do "
            "  status=$(docker inspect -f '{{.State.Running}}' labcas-publish 2>/dev/null || echo 'false'); "
            "  if [ \"$status\" = \"true\" ]; then break; fi; "
            "  echo 'Waiting for labcas-publish container...'; "
            "  sleep 5; "
            "done"
            "{% endraw %}"
        ),
    )

    # Publish using the running labcas-publish container
    publish_task = BashOperator(
        task_id="publish_metadata",
        bash_command=(
            "set -euo pipefail; "
            "docker exec "
            "-e steps=\"$PUBLISH_STEPS\" "
            "-e PUBLISH_CONSORTIUM=\"$PUBLISH_CONSORTIUM\" -e consortium=\"$PUBLISH_CONSORTIUM\" "
            "-e PUBLISH_COLLECTION=\"$PUBLISH_COLLECTION\" -e collection=\"$PUBLISH_COLLECTION\" "
            "-e PUBLISH_COLLECTION_SUBSET=\"$PUBLISH_COLLECTION_SUBSET\" -e collection_subset=\"$PUBLISH_COLLECTION_SUBSET\" "
            "-e PUBLISH_ID=\"$PUBLISH_ID\" -e publish_id=\"$PUBLISH_ID\" "
            "-e BASIC_AUTH_USER=\"$BASIC_AUTH_USER\" "
            "-e BASIC_AUTH_PASS=\"$BASIC_AUTH_PASS\" "
            "labcas-publish "
            "python3 /opt/publish/publishing_pipeline.py"
        ),
        env={
            # Use metadata generated under /metadata (mounted to /mnt/metadata in publish)
            "PUBLISH_STEPS": os.getenv("PUBLISH_STEPS", "crawl,publish"),
            "PUBLISH_CONSORTIUM": os.getenv("PUBLISH_CONSORTIUM", "NIST"),
            "PUBLISH_COLLECTION": os.getenv("PUBLISH_COLLECTION", "microbial_strain"),
            "PUBLISH_COLLECTION_SUBSET": os.getenv("PUBLISH_COLLECTION_SUBSET", ""),
            "PUBLISH_ID": os.getenv("PUBLISH_ID", ""),
            "BASIC_AUTH_USER": basic_auth_user,
            "BASIC_AUTH_PASS": basic_auth_pass,
        },
    )

    # Optional second pass: publish files only using the publish_id from generated metadata
    publish_files_only = BashOperator(
        task_id="publish_files_only",
        bash_command=(
            "set -euo pipefail; "
            "if [ \"${RUN_PUBLISH_FILES_ONLY:-false}\" != \"true\" ]; then echo 'publish_files_only disabled'; exit 0; fi; "
            "COL_DIR=/data/generated_metadata/nist/microbial_strain; "
            "PID=$(find \"$COL_DIR\" -type f -name '*_labcasmet_*.json' | awk -F'_labcasmet_' '{print $2}' | awk -F'.json' '{print $1}' | sort | tail -n 1); "
            "echo Using publish_id: $PID; "
            "docker exec "
            "-e steps=\"publish\" -e PUBLISH_STEPS=\"publish\" "
            "-e PUBLISH_CONSORTIUM=\"$PUBLISH_CONSORTIUM\" -e consortium=\"$PUBLISH_CONSORTIUM\" "
            "-e PUBLISH_COLLECTION=\"$PUBLISH_COLLECTION\" -e collection=\"$PUBLISH_COLLECTION\" "
            "-e PUBLISH_ID=\"$PID\" -e publish_id=\"$PID\" "
            "-e BASIC_AUTH_USER=\"$BASIC_AUTH_USER\" -e BASIC_AUTH_PASS=\"$BASIC_AUTH_PASS\" "
            "labcas-publish python3 /opt/publish/publishing_pipeline.py"
        ),
        env={
            "PUBLISH_CONSORTIUM": os.getenv("PUBLISH_CONSORTIUM", "NIST"),
            "PUBLISH_COLLECTION": os.getenv("PUBLISH_COLLECTION", "microbial_strain"),
            "RUN_PUBLISH_FILES_ONLY": os.getenv("RUN_PUBLISH_FILES_ONLY", "false"),
            "BASIC_AUTH_USER": basic_auth_user,
            "BASIC_AUTH_PASS": basic_auth_pass,
        },
    )

    reset_task >> parse_task >> wait_publish >> publish_task >> publish_files_only
