"""Validate and optionally publish Cell Provenance metadata."""

from datetime import datetime
import os

from airflow import DAG
from airflow.operators.bash import BashOperator

from linkml_dag_utils import optional_publish_task, require_input_files, wait_for_validator


COLLECTION = os.getenv("CELL_LINKML_COLLECTION", "cell_provenance")
CELL_BUNDLE = os.getenv("CELL_LINKML_BUNDLE", "")
SCHEMA_PATH = os.getenv(
    "NIST_LINKML_SCHEMA_PATH",
    "/opt/nist-labcas-linkml/src/nist_labcas_linkml/schema/nist_labcas_linkml.yaml",
)
STAGING_ROOT = os.getenv("CELL_LINKML_STAGING_ROOT", "/data/staging/linkml/cell_provenance")
LOG_DIR = os.getenv("CELL_LINKML_LOG_DIR", "/data/logs/airflow/linkml_validation")
VALIDATOR = os.getenv("LINKML_VALIDATOR_CONTAINER_NAME", "labcas-linkml-validator")
VALIDATION_SCRIPT = os.path.join(STAGING_ROOT, "linkml_validate_extensions.py")


with DAG(
    dag_id="cell_provenance_linkml_validate_and_publish",
    start_date=datetime(2023, 1, 1),
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    params={
        "publish_enabled": os.getenv("LABCAS_PUBLISH_ENABLED", "false"),
        "publish_collection": os.getenv("LABCAS_PUBLISH_COLLECTION", COLLECTION),
    },
    tags=["linkml", "cell-provenance", "optional-solr-publish"],
) as dag:
    check_inputs = require_input_files(
        "check_validation_inputs", {"CELL_BUNDLE": CELL_BUNDLE}
    )
    wait_validator = wait_for_validator()
    validate = BashOperator(
        task_id="validate_cell_provenance",
        bash_command=r"""
set -euo pipefail
mkdir -p "$LOG_DIR" "$STAGING_ROOT"
cp -f /opt/airflow/scripts/linkml_validate_extensions.py "$VALIDATION_SCRIPT"
chmod a+r "$VALIDATION_SCRIPT"
RUN_TAG=$(echo "${AIRFLOW_CTX_DAG_RUN_ID:-manual}" | tr ':+/' '___')
LOG_FILE="$LOG_DIR/cell_provenance_linkml_${RUN_TAG}.log"
docker exec "$VALIDATOR" python "$VALIDATION_SCRIPT" \
  --cell-bundle "$CELL_BUNDLE" --schema "$SCHEMA_PATH" \
  --verbose-pass true --strict true 2>&1 | tee "$LOG_FILE"
echo 'VALIDATION_COMPLETE collection=cell_provenance'
""",
        env={
            "VALIDATOR": VALIDATOR,
            "CELL_BUNDLE": CELL_BUNDLE,
            "SCHEMA_PATH": SCHEMA_PATH,
            "VALIDATION_SCRIPT": VALIDATION_SCRIPT,
            "STAGING_ROOT": STAGING_ROOT,
            "LOG_DIR": LOG_DIR,
        },
    )
    publish = optional_publish_task(COLLECTION)

    check_inputs >> wait_validator >> validate >> publish
