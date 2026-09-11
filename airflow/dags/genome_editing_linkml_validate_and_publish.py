"""Map, validate, and optionally publish Genome Editing metadata."""

from datetime import datetime
import os

from airflow import DAG
from airflow.operators.bash import BashOperator

from linkml_dag_utils import optional_publish_task, require_input_files, wait_for_validator


COLLECTION = os.getenv("GENOME_LINKML_COLLECTION", "genome_editing")
COLLECTION_INPUT = os.getenv("GENOME_LINKML_COLLECTION_INPUT", "")
DATASET_INPUT = os.getenv("GENOME_LINKML_DATASET_INPUT", "")
FILE_INPUT = os.getenv("GENOME_LINKML_FILE_INPUT", "")
METADATA_ROOT = os.getenv("GENOME_LINKML_METADATA_ROOT", "/metadata")
ARCHIVE_ROOT = os.getenv("GENOME_LINKML_ARCHIVE_ROOT", "/data/archive/linkml")
STAGING_ROOT = os.getenv("GENOME_LINKML_STAGING_ROOT", "/data/staging/linkml/genome")
LOG_DIR = os.getenv("GENOME_LINKML_LOG_DIR", "/data/logs/airflow/linkml_validation")
VALIDATOR = os.getenv("LINKML_VALIDATOR_CONTAINER_NAME", "labcas-linkml-validator")

COLLECTION_MAPPED = os.path.join(STAGING_ROOT, "collectionlevel.yaml")
DATASET_STAGING = os.path.join(STAGING_ROOT, "datasets")
FILE_STAGING = os.path.join(STAGING_ROOT, "files")
DATASET_MANIFEST = os.path.join(DATASET_STAGING, "validation_manifest.json")
FILE_MANIFEST = os.path.join(FILE_STAGING, "file_validation_manifest.json")
MATRIX_SCRIPT = os.path.join(STAGING_ROOT, "linkml_validate_matrix.py")


with DAG(
    dag_id="genome_editing_linkml_validate_and_publish",
    start_date=datetime(2023, 1, 1),
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    params={
        "publish_enabled": os.getenv("LABCAS_PUBLISH_ENABLED", "false"),
        "publish_collection": os.getenv("LABCAS_PUBLISH_COLLECTION", COLLECTION),
    },
    tags=["linkml", "genome-editing", "optional-solr-publish"],
) as dag:
    check_inputs = require_input_files(
        "check_validation_inputs",
        {
            "COLLECTION_INPUT": COLLECTION_INPUT,
            "DATASET_INPUT": DATASET_INPUT,
            "FILE_INPUT": FILE_INPUT,
        },
    )

    map_collection = BashOperator(
        task_id="map_collection",
        bash_command=r"""
set -euo pipefail
mkdir -p "$(dirname "$COLLECTION_MAPPED")"
python /opt/airflow/scripts/parsers/genome_collection_linkml.py \
  --input-file "$COLLECTION_INPUT" --output-file "$COLLECTION_MAPPED"
echo 'MAPPED level=collection'
""",
        env={
            "COLLECTION_INPUT": COLLECTION_INPUT,
            "COLLECTION_MAPPED": COLLECTION_MAPPED,
        },
    )

    map_datasets = BashOperator(
        task_id="map_datasets",
        bash_command=r"""
set -euo pipefail
mkdir -p "$DATASET_STAGING"
python /opt/airflow/scripts/parsers/genome_mission_bulk_datasets.py \
  --input-file "$DATASET_INPUT" --output-dir "$METADATA_ROOT" \
  --staging-dir "$DATASET_STAGING" --collection "$COLLECTION" \
  --source-file "$DATASET_INPUT" --archive-root "$ARCHIVE_ROOT" \
  --publish-file-name dataset_metadata.json \
  --collection-metadata-file "$COLLECTION_INPUT"
echo 'MAPPED level=dataset'
""",
        env={
            "COLLECTION": COLLECTION,
            "COLLECTION_INPUT": COLLECTION_INPUT,
            "DATASET_INPUT": DATASET_INPUT,
            "DATASET_STAGING": DATASET_STAGING,
            "METADATA_ROOT": METADATA_ROOT,
            "ARCHIVE_ROOT": ARCHIVE_ROOT,
        },
    )

    map_files = BashOperator(
        task_id="map_files",
        bash_command=r"""
set -euo pipefail
mkdir -p "$FILE_STAGING"
python /opt/airflow/scripts/parsers/genome_mission_bulk_files.py \
  --input-file "$FILE_INPUT" --output-dir "$METADATA_ROOT" \
  --archive-root "$ARCHIVE_ROOT" --staging-dir "$FILE_STAGING" \
  --collection "$COLLECTION" --touch-missing-files false
echo 'MAPPED level=file'
""",
        env={
            "COLLECTION": COLLECTION,
            "FILE_INPUT": FILE_INPUT,
            "FILE_STAGING": FILE_STAGING,
            "METADATA_ROOT": METADATA_ROOT,
            "ARCHIVE_ROOT": ARCHIVE_ROOT,
        },
    )

    wait_validator = wait_for_validator()

    validate = BashOperator(
        task_id="validate_collection_datasets_files",
        bash_command=r"""
set -euo pipefail
mkdir -p "$LOG_DIR" "$STAGING_ROOT"
cp -f /opt/airflow/scripts/linkml_validate_matrix.py "$MATRIX_SCRIPT"
chmod a+r "$MATRIX_SCRIPT"
RUN_TAG=$(echo "${AIRFLOW_CTX_DAG_RUN_ID:-manual}" | tr ':+/' '___')
LOG_FILE="$LOG_DIR/genome_linkml_${RUN_TAG}.log"
docker exec "$VALIDATOR" python "$MATRIX_SCRIPT" \
  --collection-input "$COLLECTION_MAPPED" \
  --dataset-manifest "$DATASET_MANIFEST" \
  --file-manifest "$FILE_MANIFEST" \
  --primary-level-map collection:CollectionLevel,dataset:DatasetLevel,file:FileLevel \
  --cross-classes '' --cross-levels dataset,file \
  --strict-primary true --strict-cross false --verbose-pass true \
  2>&1 | tee "$LOG_FILE"
echo 'VALIDATION_COMPLETE collection=genome_editing'
""",
        env={
            "VALIDATOR": VALIDATOR,
            "MATRIX_SCRIPT": MATRIX_SCRIPT,
            "COLLECTION_MAPPED": COLLECTION_MAPPED,
            "DATASET_MANIFEST": DATASET_MANIFEST,
            "FILE_MANIFEST": FILE_MANIFEST,
            "LOG_DIR": LOG_DIR,
            "STAGING_ROOT": STAGING_ROOT,
        },
    )

    publish = optional_publish_task(COLLECTION)

    check_inputs >> map_collection >> map_datasets >> map_files >> wait_validator >> validate >> publish
