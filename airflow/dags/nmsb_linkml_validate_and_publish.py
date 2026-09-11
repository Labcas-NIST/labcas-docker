"""Normalize, validate, and optionally publish NMSB metadata."""

from datetime import datetime
import os

from airflow import DAG
from airflow.operators.bash import BashOperator

from linkml_dag_utils import optional_publish_task, require_input_files, wait_for_validator


COLLECTION = os.getenv("NMSB_LINKML_COLLECTION", "nmsb")
COLLECTION_WORKBOOK = os.getenv("NMSB_COLLECTION_WORKBOOK", "")
DATASET_WORKBOOK = os.getenv("NMSB_DATASET_WORKBOOK", "")
ELAB_JSON = os.getenv("NMSB_ELAB_JSON", "")
RECORD_ID = os.getenv("NMSB_RECORD_ID", "")
DATASET_ID = os.getenv("NMSB_DATASET_ID", "")
OUTPUT_FILE = os.getenv("NMSB_LINKML_OUTPUT", "/data/staging/linkml/nmsb/record.yaml")
REPORT_FILE = os.getenv(
    "NMSB_LINKML_REPORT", "/data/staging/linkml/nmsb/normalization.json"
)
LOG_DIR = os.getenv("NMSB_LINKML_LOG_DIR", "/data/logs/airflow/linkml_validation")
VALIDATOR = os.getenv("LINKML_VALIDATOR_CONTAINER_NAME", "labcas-linkml-validator")


with DAG(
    dag_id="nmsb_linkml_validate_and_publish",
    start_date=datetime(2023, 1, 1),
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    params={
        "publish_enabled": os.getenv("LABCAS_PUBLISH_ENABLED", "false"),
        "publish_collection": os.getenv("LABCAS_PUBLISH_COLLECTION", COLLECTION),
    },
    tags=["linkml", "nmsb", "optional-solr-publish"],
) as dag:
    check_inputs = require_input_files(
        "check_validation_inputs",
        {
            "COLLECTION_WORKBOOK": COLLECTION_WORKBOOK,
            "DATASET_WORKBOOK": DATASET_WORKBOOK,
            "ELAB_JSON": ELAB_JSON,
        },
    )

    check_identifiers = BashOperator(
        task_id="check_runtime_identifiers",
        bash_command=r"""
set -euo pipefail
test -n "$RECORD_ID" || { echo 'NMSB_RECORD_ID is required' >&2; exit 1; }
test -n "$DATASET_ID" || { echo 'NMSB_DATASET_ID is required' >&2; exit 1; }
echo 'IDENTIFIERS_READY'
""",
        env={"RECORD_ID": RECORD_ID, "DATASET_ID": DATASET_ID},
    )

    normalize = BashOperator(
        task_id="normalize_metadata",
        bash_command=r"""
set -euo pipefail
python /opt/airflow/scripts/parsers/nmsb_linkml.py \
  --collection-workbook "$COLLECTION_WORKBOOK" \
  --dataset-workbook "$DATASET_WORKBOOK" --elab-json "$ELAB_JSON" \
  --output "$OUTPUT_FILE" --report "$REPORT_FILE" \
  --nist-id "$RECORD_ID" --dataset-id "$DATASET_ID"
echo 'NORMALIZATION_COMPLETE collection=nmsb'
""",
        env={
            "COLLECTION_WORKBOOK": COLLECTION_WORKBOOK,
            "DATASET_WORKBOOK": DATASET_WORKBOOK,
            "ELAB_JSON": ELAB_JSON,
            "OUTPUT_FILE": OUTPUT_FILE,
            "REPORT_FILE": REPORT_FILE,
            "RECORD_ID": RECORD_ID,
            "DATASET_ID": DATASET_ID,
        },
    )

    wait_validator = wait_for_validator()

    validate = BashOperator(
        task_id="validate_nmsb_metadata",
        bash_command=r"""
set -euo pipefail
mkdir -p "$LOG_DIR"
RUN_TAG=$(echo "${AIRFLOW_CTX_DAG_RUN_ID:-manual}" | tr ':+/' '___')
LOG_FILE="$LOG_DIR/nmsb_linkml_${RUN_TAG}.log"
docker exec "$VALIDATOR" python /opt/linkml/linkml_validate.py \
  --input "$OUTPUT_FILE" --class-name NMSBCollection \
  2>&1 | tee "$LOG_FILE"
echo 'VALIDATION_COMPLETE collection=nmsb'
""",
        env={
            "VALIDATOR": VALIDATOR,
            "OUTPUT_FILE": OUTPUT_FILE,
            "LOG_DIR": LOG_DIR,
        },
    )

    publish = optional_publish_task(COLLECTION)

    check_inputs >> check_identifiers >> normalize >> wait_validator >> validate >> publish
