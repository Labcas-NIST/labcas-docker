"""Validate and optionally publish Flow Cytometry metadata."""

from datetime import datetime
import os

from airflow import DAG
from airflow.operators.bash import BashOperator

from linkml_dag_utils import optional_publish_task, wait_for_validator


COLLECTION = os.getenv("FLOW_LINKML_COLLECTION", "flow_cytometry")
STAGING_ROOT = os.getenv("FLOW_LINKML_STAGING_ROOT", "/data/staging/linkml/flow_cytometry")
FLOW_INPUT_DIR = os.getenv("FLOW_LINKML_INPUT_DIR", "")
FLOW_MANIFEST = os.getenv(
    "FLOW_LINKML_MANIFEST",
    os.path.join(STAGING_ROOT, COLLECTION, f"{COLLECTION}.manifest.json"),
)
LOG_DIR = os.getenv("FLOW_LINKML_LOG_DIR", "/data/logs/airflow/linkml_validation")
VALIDATOR = os.getenv("LINKML_VALIDATOR_CONTAINER_NAME", "labcas-linkml-validator")
VALIDATION_SCRIPT = os.path.join(STAGING_ROOT, "linkml_validate_extensions.py")


with DAG(
    dag_id="flow_cytometry_linkml_validate_and_publish",
    start_date=datetime(2023, 1, 1),
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    params={
        "publish_enabled": os.getenv("LABCAS_PUBLISH_ENABLED", "false"),
        "publish_collection": os.getenv("LABCAS_PUBLISH_COLLECTION", COLLECTION),
    },
    tags=["linkml", "flow-cytometry", "optional-solr-publish"],
) as dag:
    check_inputs = BashOperator(
        task_id="check_validation_inputs",
        bash_command=r"""
set -euo pipefail
if [ -n "$FLOW_INPUT_DIR" ]; then
  test -d "$FLOW_INPUT_DIR" || { echo 'FLOW_LINKML_INPUT_DIR is not a directory' >&2; exit 1; }
  echo 'INPUT_READY source=flow_cytometry_directory'
elif [ -s "$FLOW_MANIFEST" ]; then
  echo 'INPUT_READY source=flow_cytometry_manifest'
else
  echo 'Set FLOW_LINKML_INPUT_DIR or FLOW_LINKML_MANIFEST to runtime metadata' >&2
  exit 1
fi
""",
        env={"FLOW_INPUT_DIR": FLOW_INPUT_DIR, "FLOW_MANIFEST": FLOW_MANIFEST},
    )
    normalize = BashOperator(
        task_id="normalize_metadata",
        bash_command=r"""
set -euo pipefail
if [ -n "$FLOW_INPUT_DIR" ]; then
  python /opt/airflow/scripts/parsers/flow_cytometry.py \
    --input-dir "$FLOW_INPUT_DIR" --output-dir "$STAGING_ROOT" \
    --collection "$COLLECTION" --manifest-only
fi
test -s "$FLOW_MANIFEST" || { echo 'Normalized Flow Cytometry manifest was not produced' >&2; exit 1; }
echo 'NORMALIZATION_COMPLETE collection=flow_cytometry'
""",
        env={
            "FLOW_INPUT_DIR": FLOW_INPUT_DIR,
            "FLOW_MANIFEST": FLOW_MANIFEST,
            "STAGING_ROOT": STAGING_ROOT,
            "COLLECTION": COLLECTION,
        },
    )
    wait_validator = wait_for_validator()
    validate = BashOperator(
        task_id="validate_flow_cytometry",
        bash_command=r"""
set -euo pipefail
mkdir -p "$LOG_DIR" "$STAGING_ROOT"
cp -f /opt/airflow/scripts/linkml_validate_extensions.py "$VALIDATION_SCRIPT"
chmod a+r "$VALIDATION_SCRIPT"
RUN_TAG=$(echo "${AIRFLOW_CTX_DAG_RUN_ID:-manual}" | tr ':+/' '___')
LOG_FILE="$LOG_DIR/flow_cytometry_linkml_${RUN_TAG}.log"
docker exec "$VALIDATOR" python "$VALIDATION_SCRIPT" \
  --flow-manifest "$FLOW_MANIFEST" --verbose-pass true --strict true \
  2>&1 | tee "$LOG_FILE"
echo 'VALIDATION_COMPLETE collection=flow_cytometry'
""",
        env={
            "VALIDATOR": VALIDATOR,
            "FLOW_MANIFEST": FLOW_MANIFEST,
            "VALIDATION_SCRIPT": VALIDATION_SCRIPT,
            "STAGING_ROOT": STAGING_ROOT,
            "LOG_DIR": LOG_DIR,
        },
    )
    publish = optional_publish_task(COLLECTION)

    check_inputs >> normalize >> wait_validator >> validate >> publish
