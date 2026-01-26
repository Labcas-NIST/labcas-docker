from datetime import datetime
from airflow import DAG
from airflow.operators.bash import BashOperator
import os


with DAG(
    dag_id="parse_and_publish_ephemeral",
    start_date=datetime(2023, 1, 1),
    schedule_interval='@once',
    catchup=False,
    max_active_runs=2,
    is_paused_upon_creation=False,
) as dag:

    # Inputs/outputs mapping (kept identical to the existing DAG):
    # - Input CSV: /data/raw/Basophile.csv (host: ./data/raw/Basophile.csv)
    # - Parsed cfg: /data/staging/Basophile/Basophile.cfg
    # - Archive output: /data/archive (for this ephemeral run, we bind a separate host directory)

    # Base and ephemeral collection names
    base_collection = os.getenv("PUBLISH_COLLECTION", "Basophile")
    ephemeral_collection = f"{base_collection}_ephemeral"

    parse_task = BashOperator(
        task_id="parse_excel",
        bash_command=(
            "set -euxo pipefail; "
            "ls -al /data || true; "
            f"python /opt/airflow/scripts/parse_excel.py /data/raw/{base_collection}.csv /data/staging/{ephemeral_collection}/{ephemeral_collection}.cfg"
        ),
    )

    # Snapshot counts before run (for easy comparison)
    snapshot_before = BashOperator(
        task_id="snapshot_before",
        bash_command=(
            "set -euo pipefail; "
            "echo '--- BEFORE ---'; "
            "echo 'staging files:'; find /data/staging -type f | wc -l || true; "
            "echo 'archive files:'; find /data/archive -type f | wc -l || true; "
            "du -sh /data/archive || true"
        ),
    )

    # Prepare an ephemeral config by ensuring the CollectionName has the suffix.
    prepare_ephemeral_cfg = BashOperator(
        task_id="prepare_ephemeral_cfg",
        bash_command=(
            "set -euo pipefail; "
            f"dst_dir=/data/staging/{ephemeral_collection}; "
            f"dst_cfg=$dst_dir/{ephemeral_collection}.cfg; "
            "echo \"Ensuring ephemeral cfg: $dst_cfg\"; "
            "if [ ! -f \"$dst_cfg\" ]; then echo 'Ephemeral cfg not found' >&2; exit 1; fi; "
            f"sed -i 's/^CollectionName=.*/CollectionName={ephemeral_collection}/' \"$dst_cfg\"; "
            "echo 'Ephemeral cfg prepared.'"
        ),
    )

    # Copy the ephemeral cfg into /metadata so the publish container sees it at /mnt/metadata
    sync_to_metadata = BashOperator(
        task_id="sync_to_metadata",
        bash_command=(
            "set -euo pipefail; "
            f"src=/data/staging/{ephemeral_collection}/{ephemeral_collection}.cfg; "
            f"dst_dir=/metadata/{ephemeral_collection}; mkdir -p \"$dst_dir\"; "
            f"cp -f \"$src\" \"$dst_dir/\"; "
            "echo 'Copied ephemeral cfg to /metadata'"
        ),
    )

    # Wait for Solr to be ready before launching the ephemeral publish container.
    # This avoids transient failures where the backend container is up but Solr
    # has not finished binding to 8984 yet.
    wait_solr = BashOperator(
        task_id="wait_solr",
        bash_command=(
            "set -euo pipefail; "
            "for i in {1..60}; do "
            "  if curl -skf https://labcas-backend:8984/solr/admin/info/system >/dev/null; then echo 'Solr is ready'; exit 0; fi; "
            "  echo 'Waiting for Solr (attempt' $i ')'; sleep 5; "
            "done; echo 'Solr not ready in time' >&2; exit 1"
        ),
    )

    # Credentials and runtime settings
    basic_auth_user = os.getenv("BASIC_AUTH_USER", "dliu")
    basic_auth_pass = os.getenv("BASIC_AUTH_PASS", "secret")

    # Use a distinct collection name for ephemeral runs so it's easy
    # to verify in the UI/Solr without clobbering the main collection.

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

    publish_ephemeral = BashOperator(
        task_id="publish_ephemeral",
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
            "bash -lc 'mkdir -p /data/archive/nist/${PUBLISH_COLLECTION} && python3 /opt/publish/publishing_pipeline.py'"
        ),
        env={
            "PUBLISH_STEPS": os.getenv("PUBLISH_STEPS", "crawl,publish"),
            "PUBLISH_CONSORTIUM": os.getenv("PUBLISH_CONSORTIUM", "NIST"),
            "PUBLISH_COLLECTION": ephemeral_collection,
            "PUBLISH_COLLECTION_SUBSET": os.getenv("PUBLISH_COLLECTION_SUBSET", ""),
            "PUBLISH_ID": os.getenv("PUBLISH_ID", "ephemeral"),
            "SOLR_URL": os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/"),
            "solr": os.getenv("solr", os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/")),
            "BASIC_AUTH_USER": basic_auth_user,
            "BASIC_AUTH_PASS": basic_auth_pass,
        },
    )

    snapshot_after = BashOperator(
        task_id="snapshot_after",
        bash_command=(
            "set -euo pipefail; "
            "echo '--- AFTER ---'; "
            "echo 'staging files:'; find /data/staging -type f | wc -l || true; "
            "echo 'archive files:'; find /data/archive -type f | wc -l || true; "
            "du -sh /data/archive || true; "
            "echo 'Recent archive files:'; find /data/archive -type f -mtime -1 | tail -n 50 || true"
        ),
    )

    # As a visibility aid, insert a lightweight marker doc into the
    # collections core for the ephemeral collection if it doesn't exist.
    post_solr_marker = BashOperator(
        task_id="post_solr_marker",
        bash_command=(
            "set -euo pipefail; "
            f"if curl -sk --fail 'https://labcas-backend:8984/solr/collections/select?wt=json&q=id:{ephemeral_collection}' | grep -q '" + '"numFound":1' + "'; then "
            "  echo 'Ephemeral collection already present in Solr'; exit 0; "
            "fi; "
            f"printf '[{{" + '"id"' + ":" + '"{ephemeral_collection}"' + "," + '"CollectionName"' + ":" + '"{ephemeral_collection}"' + "," + '"CollectionDescription"' + ":" + '"Ephemeral test via DAG"' + "}}]' > /tmp/ephemeral_add.json; "
            "curl -sk -H 'Content-Type: application/json' --data-binary @/tmp/ephemeral_add.json 'https://labcas-backend:8984/solr/collections/update?commit=true' && echo 'Marker doc inserted'"
        ),
    )

    # Pipeline
    parse_task >> snapshot_before >> prepare_ephemeral_cfg >> sync_to_metadata >> wait_solr >> wait_publish >> publish_ephemeral >> post_solr_marker >> snapshot_after
