from datetime import datetime
import os

from airflow import DAG
from airflow.operators.bash import BashOperator


with DAG(
    dag_id="genomic_helloworld_linkml_validation",
    start_date=datetime(2023, 1, 1),
    schedule_interval="@once",
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
) as dag:
    collection_name = os.getenv(
        "GENOMIC_HELLOWORLD_COLLECTION", "genome_editing_consortium"
    )
    dataset_name = os.getenv("GENOMIC_HELLOWORLD_DATASET", "interlab")
    file_name = os.getenv(
        "GENOMIC_HELLOWORLD_FILE_NAME", "collection_metadata.json"
    )

    collection_metadata_file = os.getenv(
        "GENOMIC_HELLOWORLD_COLLECTION_METADATA",
        "/data/raw/genome_editing_consortium/collection_metadata.json",
    )
    dataset_metadata_file = os.getenv(
        "GENOMIC_HELLOWORLD_DATASET_METADATA",
        "/data/raw/genome_editing_consortium/dataset_metadata.json",
    )
    file_metadata_file = os.getenv(
        "GENOMIC_HELLOWORLD_FILE_METADATA",
        "/data/raw/genome_editing_consortium/file_metadata.json",
    )

    collection_mapped_file = os.getenv(
        "GENOMIC_HELLOWORLD_COLLECTION_MAPPED",
        "/data/staging/genome_editing_consortium/collectionlevel.yaml",
    )
    dataset_manifest_file = os.getenv(
        "GENOMIC_HELLOWORLD_DATASET_MANIFEST",
        "/data/staging/genome_editing_consortium/bulk/validation_manifest.json",
    )
    file_manifest_file = os.getenv(
        "GENOMIC_HELLOWORLD_FILE_MANIFEST",
        "/data/staging/genome_editing_consortium/files_bulk/file_validation_manifest.json",
    )
    validation_matrix_script = os.getenv(
        "GENOMIC_HELLOWORLD_LINKML_MATRIX_SCRIPT",
        "/data/staging/genome_editing_consortium/linkml_validate_matrix.py",
    )
    linkml_log_dir = os.getenv(
        "GENOMIC_HELLOWORLD_LINKML_LOG_DIR",
        "/data/logs/airflow/linkml_validation",
    )

    metadata_root = os.getenv("GENOMIC_HELLOWORLD_METADATA_ROOT", "/metadata")
    archive_root = os.getenv("GENOMIC_HELLOWORLD_ARCHIVE_ROOT", "/data/archive/nist")

    primary_level_map = os.getenv(
        "GENOMIC_HELLOWORLD_LINKML_PRIMARY_MAP",
        "collection:CollectionLevel,dataset:Datasetlevel,file:FileLevel",
    )
    cross_classes = os.getenv(
        "GENOMIC_HELLOWORLD_LINKML_CROSS_CLASSES",
        "ALL_OTHERS",
    )
    cross_levels = os.getenv(
        "GENOMIC_HELLOWORLD_LINKML_CROSS_LEVELS", "dataset,file"
    )
    strict_primary = os.getenv("GENOMIC_HELLOWORLD_LINKML_STRICT_PRIMARY", "true")
    strict_cross = os.getenv("GENOMIC_HELLOWORLD_LINKML_STRICT_CROSS", "false")

    validator_container = os.getenv(
        "LINKML_VALIDATOR_CONTAINER_NAME", "labcas-linkml-validator"
    )
    publish_container = os.getenv("PUBLISH_CONTAINER_NAME", "labcas-publish")
    basic_auth_user = os.getenv("BASIC_AUTH_USER", "dliu")
    basic_auth_pass = os.getenv("BASIC_AUTH_PASS", "secret")

    reset_generated_state = BashOperator(
        task_id="reset_generated_state",
        bash_command=(
            "set -euo pipefail; "
            "if [ \"${RESET_BEFORE_RUN:-false}\" != \"true\" ]; then echo 'Reset disabled'; exit 0; fi; "
            f"rm -rf '/metadata/{collection_name}' || true; "
            f"rm -rf '/data/archive/nist/{collection_name}' || true; "
            f"rm -rf '/data/generated_metadata/nist/{collection_name}' || true; "
            "echo 'Reset complete'"
        ),
    )

    ensure_input_files = BashOperator(
        task_id="ensure_input_files",
        bash_command=(
            "set -euo pipefail; "
            f"mkdir -p \"$(dirname '{collection_metadata_file}')\"; "
            f"mkdir -p \"$(dirname '{dataset_metadata_file}')\"; "
            f"mkdir -p \"$(dirname '{file_metadata_file}')\"; "
            f"if [ ! -s '{collection_metadata_file}' ]; then "
            f"  cat > '{collection_metadata_file}' <<'JSON'\n"
            "{\n"
            "  \"CollectionName\": \"NIST Genome Editing Consortium\",\n"
            "  \"CollectionDescription\": \"Auto-generated placeholder collection metadata.\",\n"
            "  \"LeadPoC\": [\"Unknown Principal Contact\"],\n"
            "  \"LeadPoCEmail\": [\"unknown@example.org\"],\n"
            "  \"StudyType\": [\"Interlab\"]\n"
            "}\n"
            "JSON\n"
            "fi; "
            f"if [ ! -s '{dataset_metadata_file}' ]; then "
            f"  cat > '{dataset_metadata_file}' <<'JSON'\n"
            "{\n"
            "  \"response\": {\n"
            "    \"docs\": [\n"
            "      {\n"
            "        \"DatasetId\": \"genome_editing_consortium/interlab\",\n"
            "        \"DatasetName\": \"interlab\",\n"
            "        \"CollectionId\": \"genome_editing_consortium\",\n"
            "        \"CollectionName\": \"genome_editing_consortium\",\n"
            "        \"CollectionDescription\": \"Auto-generated placeholder dataset metadata.\",\n"
            "        \"AssayType\": \"DNA sequencing\"\n"
            "      }\n"
            "    ]\n"
            "  }\n"
            "}\n"
            "JSON\n"
            "fi; "
            f"if [ ! -s '{file_metadata_file}' ]; then "
            f"  cat > '{file_metadata_file}' <<'JSON'\n"
            "{\n"
            "  \"response\": {\n"
            "    \"docs\": [\n"
            "      {\n"
            "        \"id\": \"genome_editing_consortium/interlab/collection_metadata.json\",\n"
            "        \"DatasetId\": \"genome_editing_consortium/interlab\",\n"
            "        \"DatasetName\": \"interlab\",\n"
            "        \"CollectionId\": \"genome_editing_consortium\",\n"
            "        \"CollectionName\": \"genome_editing_consortium\",\n"
            "        \"FileName\": \"collection_metadata.json\",\n"
            "        \"FileType\": \"json\",\n"
            "        \"FileSize\": \"0\",\n"
            "        \"MIMEType\": \"application/json\",\n"
            "        \"DataProcessingLevel\": \"raw\",\n"
            "        \"DataFileContext\": \"deliverable_data\",\n"
            "        \"FileContentType\": \"documentation\"\n"
            "      }\n"
            "    ]\n"
            "  }\n"
            "}\n"
            "JSON\n"
            "fi"
        ),
    )

    map_collection_payload = BashOperator(
        task_id="map_collection_payload",
        bash_command=(
            "set -euxo pipefail; "
            "python /opt/airflow/scripts/parsers/genome_collection_linkml.py "
            f"--input-file '{collection_metadata_file}' "
            f"--output-file '{collection_mapped_file}'"
        ),
    )

    generate_dataset_bulk_cfg = BashOperator(
        task_id="generate_dataset_bulk_cfg",
        bash_command=(
            "set -euxo pipefail; "
            "python /opt/airflow/scripts/parsers/genome_mission_bulk_datasets.py "
            f"--input-file '{dataset_metadata_file}' "
            "--output-dir \"$GENOMIC_HELLOWORLD_METADATA_ROOT\" "
            "--staging-dir \"$GENOMIC_HELLOWORLD_DATASET_STAGING_DIR\" "
            "--collection \"$GENOMIC_HELLOWORLD_COLLECTION\" "
            f"--source-file '{dataset_metadata_file}' "
            "--archive-root \"$GENOMIC_HELLOWORLD_ARCHIVE_ROOT\" "
            "--publish-file-name \"dataset_metadata.json\" "
            f"--collection-metadata-file '{collection_metadata_file}'"
        ),
        env={
            "GENOMIC_HELLOWORLD_METADATA_ROOT": metadata_root,
            "GENOMIC_HELLOWORLD_DATASET_STAGING_DIR": os.path.dirname(
                dataset_manifest_file
            ),
            "GENOMIC_HELLOWORLD_COLLECTION": collection_name,
            "GENOMIC_HELLOWORLD_ARCHIVE_ROOT": archive_root,
        },
    )

    generate_file_bulk_cfg = BashOperator(
        task_id="generate_file_bulk_cfg",
        bash_command=(
            "set -euxo pipefail; "
            "python /opt/airflow/scripts/parsers/genome_mission_bulk_files.py "
            f"--input-file '{file_metadata_file}' "
            "--output-dir \"$GENOMIC_HELLOWORLD_METADATA_ROOT\" "
            "--archive-root \"$GENOMIC_HELLOWORLD_ARCHIVE_ROOT\" "
            "--staging-dir \"$GENOMIC_HELLOWORLD_FILE_STAGING_DIR\" "
            "--collection \"$GENOMIC_HELLOWORLD_COLLECTION\" "
            "--touch-missing-files \"true\""
        ),
        env={
            "GENOMIC_HELLOWORLD_METADATA_ROOT": metadata_root,
            "GENOMIC_HELLOWORLD_FILE_STAGING_DIR": os.path.dirname(file_manifest_file),
            "GENOMIC_HELLOWORLD_COLLECTION": collection_name,
            "GENOMIC_HELLOWORLD_ARCHIVE_ROOT": archive_root,
        },
    )

    wait_validator_container = BashOperator(
        task_id="wait_validator_container",
        bash_command=(
            "{% raw %}"
            "set -euo pipefail; "
            "while true; do "
            "  status=$(docker inspect -f '{{.State.Running}}' \"$LINKML_VALIDATOR_CONTAINER_NAME\" 2>/dev/null || echo 'false'); "
            "  if [ \"$status\" = \"true\" ]; then break; fi; "
            "  echo 'Waiting for LinkML validator container...'; "
            "  sleep 5; "
            "done"
            "{% endraw %}"
        ),
        env={"LINKML_VALIDATOR_CONTAINER_NAME": validator_container},
    )

    stage_validation_matrix_script = BashOperator(
        task_id="stage_validation_matrix_script",
        bash_command=(
            "set -euxo pipefail; "
            "mkdir -p \"$(dirname \"$GENOMIC_HELLOWORLD_LINKML_MATRIX_SCRIPT\")\"; "
            "cp -f /opt/airflow/scripts/linkml_validate_matrix.py \"$GENOMIC_HELLOWORLD_LINKML_MATRIX_SCRIPT\"; "
            "chmod a+r \"$GENOMIC_HELLOWORLD_LINKML_MATRIX_SCRIPT\""
        ),
        env={"GENOMIC_HELLOWORLD_LINKML_MATRIX_SCRIPT": validation_matrix_script},
    )

    validate_linkml_matrix = BashOperator(
        task_id="validate_linkml_matrix",
        bash_command=(
            "set -euxo pipefail; "
            "mkdir -p \"$GENOMIC_HELLOWORLD_LINKML_LOG_DIR\"; "
            "RUN_TAG=$(echo \"${AIRFLOW_CTX_DAG_RUN_ID:-manual}\" | tr ':+/' '___'); "
            "LOG_FILE=\"$GENOMIC_HELLOWORLD_LINKML_LOG_DIR/genomic_helloworld_linkml_validation_${RUN_TAG}.log\"; "
            "docker exec \"$LINKML_VALIDATOR_CONTAINER_NAME\" "
            "python \"$GENOMIC_HELLOWORLD_LINKML_MATRIX_SCRIPT\" "
            "--collection-input \"$GENOMIC_HELLOWORLD_COLLECTION_MAPPED\" "
            "--dataset-manifest \"$GENOMIC_HELLOWORLD_DATASET_MANIFEST\" "
            "--file-manifest \"$GENOMIC_HELLOWORLD_FILE_MANIFEST\" "
            "--primary-level-map \"$GENOMIC_HELLOWORLD_LINKML_PRIMARY_MAP\" "
            "--cross-classes \"$GENOMIC_HELLOWORLD_LINKML_CROSS_CLASSES\" "
            "--cross-levels \"$GENOMIC_HELLOWORLD_LINKML_CROSS_LEVELS\" "
            "--strict-primary \"$GENOMIC_HELLOWORLD_LINKML_STRICT_PRIMARY\" "
            "--strict-cross \"$GENOMIC_HELLOWORLD_LINKML_STRICT_CROSS\" "
            "2>&1 | tee \"$LOG_FILE\"; "
            "echo \"Wrote LinkML validation log: $LOG_FILE\""
        ),
        env={
            "LINKML_VALIDATOR_CONTAINER_NAME": validator_container,
            "GENOMIC_HELLOWORLD_LINKML_MATRIX_SCRIPT": validation_matrix_script,
            "GENOMIC_HELLOWORLD_COLLECTION_MAPPED": collection_mapped_file,
            "GENOMIC_HELLOWORLD_DATASET_MANIFEST": dataset_manifest_file,
            "GENOMIC_HELLOWORLD_FILE_MANIFEST": file_manifest_file,
            "GENOMIC_HELLOWORLD_LINKML_PRIMARY_MAP": primary_level_map,
            "GENOMIC_HELLOWORLD_LINKML_CROSS_CLASSES": cross_classes,
            "GENOMIC_HELLOWORLD_LINKML_CROSS_LEVELS": cross_levels,
            "GENOMIC_HELLOWORLD_LINKML_STRICT_PRIMARY": strict_primary,
            "GENOMIC_HELLOWORLD_LINKML_STRICT_CROSS": strict_cross,
            "GENOMIC_HELLOWORLD_LINKML_LOG_DIR": linkml_log_dir,
        },
    )

    wait_publish_container = BashOperator(
        task_id="wait_publish_container",
        bash_command=(
            "{% raw %}"
            "set -euo pipefail; "
            "while true; do "
            "  status=$(docker inspect -f '{{.State.Running}}' \"$PUBLISH_CONTAINER_NAME\" 2>/dev/null || echo 'false'); "
            "  if [ \"$status\" = \"true\" ]; then break; fi; "
            "  echo 'Waiting for labcas-publish container...'; "
            "  sleep 5; "
            "done"
            "{% endraw %}"
        ),
        env={"PUBLISH_CONTAINER_NAME": publish_container},
    )

    crawl_metadata = BashOperator(
        task_id="crawl_metadata",
        bash_command=(
            "set -euo pipefail; "
            "docker exec "
            "-e steps=\"$PUBLISH_STEPS\" "
            "-e PUBLISH_CONSORTIUM=\"$PUBLISH_CONSORTIUM\" -e consortium=\"$PUBLISH_CONSORTIUM\" "
            "-e PUBLISH_COLLECTION=\"$PUBLISH_COLLECTION\" -e collection=\"$PUBLISH_COLLECTION\" "
            "-e PUBLISH_COLLECTION_SUBSET=\"$PUBLISH_COLLECTION_SUBSET\" -e collection_subset=\"$PUBLISH_COLLECTION_SUBSET\" "
            "-e PUBLISH_ID=\"$PUBLISH_ID\" -e publish_id=\"$PUBLISH_ID\" "
            "-e SOLR_URL=\"$SOLR_URL\" -e solr=\"$solr\" "
            "-e BASIC_AUTH_USER=\"$BASIC_AUTH_USER\" "
            "-e BASIC_AUTH_PASS=\"$BASIC_AUTH_PASS\" "
            "\"$PUBLISH_CONTAINER_NAME\" "
            "python3 /opt/publish/publishing_pipeline.py"
        ),
        env={
            "PUBLISH_CONTAINER_NAME": publish_container,
            "PUBLISH_STEPS": os.getenv("PUBLISH_STEPS", "crawl"),
            "PUBLISH_CONSORTIUM": os.getenv("PUBLISH_CONSORTIUM", "NIST"),
            "PUBLISH_COLLECTION": os.getenv("PUBLISH_COLLECTION", collection_name),
            "PUBLISH_COLLECTION_SUBSET": os.getenv("PUBLISH_COLLECTION_SUBSET", ""),
            "PUBLISH_ID": os.getenv("PUBLISH_ID", ""),
            "SOLR_URL": os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/"),
            "solr": os.getenv(
                "solr", os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/")
            ),
            "BASIC_AUTH_USER": basic_auth_user,
            "BASIC_AUTH_PASS": basic_auth_pass,
        },
    )

    normalize_generated_metadata = BashOperator(
        task_id="normalize_generated_metadata",
        bash_command=(
            "set -euo pipefail; "
            "if [ \"${NORMALIZE_GENERATED_METADATA:-true}\" != \"true\" ]; then echo 'normalize_generated_metadata disabled'; exit 0; fi; "
            "COL_DIR=\"/data/generated_metadata/nist/${PUBLISH_COLLECTION}\"; "
            "if [ ! -d \"$COL_DIR\" ]; then COL_DIR=\"/data/generated_metadata/${PUBLISH_COLLECTION}\"; fi; "
            "PID=$(find \"$COL_DIR\" -type f -name '*_labcasmet_*.json' | awk -F'_labcasmet_' '{print $2}' | awk -F'.json' '{print $1}' | sort | tail -n 1); "
            "if [ -z \"$PID\" ]; then echo 'No publish_id found for normalization'; exit 1; fi; "
            "python /opt/airflow/scripts/parsers/normalize_generated_metadata.py "
            "--collection \"$PUBLISH_COLLECTION\" "
            "--publish-id \"$PID\" "
            "--generated-root \"/data/generated_metadata\"; "
            "echo \"Normalized generated metadata for publish_id=$PID\""
        ),
        env={
            "PUBLISH_COLLECTION": os.getenv("PUBLISH_COLLECTION", collection_name),
            "NORMALIZE_GENERATED_METADATA": os.getenv(
                "NORMALIZE_GENERATED_METADATA", "true"
            ),
        },
    )

    publish_metadata = BashOperator(
        task_id="publish_metadata",
        bash_command=(
            "set -euo pipefail; "
            "COL_DIR=\"/data/generated_metadata/nist/${PUBLISH_COLLECTION}\"; "
            "if [ ! -d \"$COL_DIR\" ]; then COL_DIR=\"/data/generated_metadata/${PUBLISH_COLLECTION}\"; fi; "
            "PID=$(find \"$COL_DIR\" -type f -name '*_labcasmet_*.json' | awk -F'_labcasmet_' '{print $2}' | awk -F'.json' '{print $1}' | sort | tail -n 1); "
            "if [ -z \"$PID\" ]; then echo 'No publish_id found for publish step'; exit 1; fi; "
            "echo Using publish_id: $PID; "
            "docker exec "
            "-e steps=\"publish\" -e PUBLISH_STEPS=\"publish\" "
            "-e PUBLISH_CONSORTIUM=\"$PUBLISH_CONSORTIUM\" -e consortium=\"$PUBLISH_CONSORTIUM\" "
            "-e PUBLISH_COLLECTION=\"$PUBLISH_COLLECTION\" -e collection=\"$PUBLISH_COLLECTION\" "
            "-e PUBLISH_COLLECTION_SUBSET=\"$PUBLISH_COLLECTION_SUBSET\" -e collection_subset=\"$PUBLISH_COLLECTION_SUBSET\" "
            "-e PUBLISH_ID=\"$PID\" -e publish_id=\"$PID\" "
            "-e SOLR_URL=\"$SOLR_URL\" -e solr=\"$solr\" "
            "-e BASIC_AUTH_USER=\"$BASIC_AUTH_USER\" "
            "-e BASIC_AUTH_PASS=\"$BASIC_AUTH_PASS\" "
            "\"$PUBLISH_CONTAINER_NAME\" "
            "python3 /opt/publish/publishing_pipeline.py"
        ),
        env={
            "PUBLISH_CONTAINER_NAME": publish_container,
            "PUBLISH_CONSORTIUM": os.getenv("PUBLISH_CONSORTIUM", "NIST"),
            "PUBLISH_COLLECTION": os.getenv("PUBLISH_COLLECTION", collection_name),
            "PUBLISH_COLLECTION_SUBSET": os.getenv("PUBLISH_COLLECTION_SUBSET", ""),
            "SOLR_URL": os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/"),
            "solr": os.getenv(
                "solr", os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/")
            ),
            "BASIC_AUTH_USER": basic_auth_user,
            "BASIC_AUTH_PASS": basic_auth_pass,
        },
    )

    publish_files_only = BashOperator(
        task_id="publish_files_only",
        bash_command=(
            "set -euo pipefail; "
            "if [ \"${RUN_PUBLISH_FILES_ONLY:-false}\" != \"true\" ]; then echo 'publish_files_only disabled'; exit 0; fi; "
            "COL_DIR=\"/data/generated_metadata/nist/${PUBLISH_COLLECTION}\"; "
            "if [ ! -d \"$COL_DIR\" ]; then COL_DIR=\"/data/generated_metadata/${PUBLISH_COLLECTION}\"; fi; "
            "PID=$(find \"$COL_DIR\" -type f -name '*_labcasmet_*.json' | awk -F'_labcasmet_' '{print $2}' | awk -F'.json' '{print $1}' | sort | tail -n 1); "
            "echo Using publish_id: $PID; "
            "docker exec "
            "-e steps=\"publish\" -e PUBLISH_STEPS=\"publish\" "
            "-e PUBLISH_CONSORTIUM=\"$PUBLISH_CONSORTIUM\" -e consortium=\"$PUBLISH_CONSORTIUM\" "
            "-e PUBLISH_COLLECTION=\"$PUBLISH_COLLECTION\" -e collection=\"$PUBLISH_COLLECTION\" "
            "-e PUBLISH_ID=\"$PID\" -e publish_id=\"$PID\" "
            "-e SOLR_URL=\"$SOLR_URL\" -e solr=\"$solr\" "
            "-e BASIC_AUTH_USER=\"$BASIC_AUTH_USER\" -e BASIC_AUTH_PASS=\"$BASIC_AUTH_PASS\" "
            "\"$PUBLISH_CONTAINER_NAME\" "
            "python3 /opt/publish/publishing_pipeline.py"
        ),
        env={
            "PUBLISH_CONTAINER_NAME": publish_container,
            "PUBLISH_CONSORTIUM": os.getenv("PUBLISH_CONSORTIUM", "NIST"),
            "PUBLISH_COLLECTION": os.getenv("PUBLISH_COLLECTION", collection_name),
            "RUN_PUBLISH_FILES_ONLY": os.getenv("RUN_PUBLISH_FILES_ONLY", "false"),
            "SOLR_URL": os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/"),
            "solr": os.getenv(
                "solr", os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/")
            ),
            "BASIC_AUTH_USER": basic_auth_user,
            "BASIC_AUTH_PASS": basic_auth_pass,
        },
    )

    (
        reset_generated_state
        >> ensure_input_files
        >> map_collection_payload
        >> generate_dataset_bulk_cfg
        >> generate_file_bulk_cfg
        >> wait_validator_container
        >> stage_validation_matrix_script
        >> validate_linkml_matrix
        >> wait_publish_container
        >> crawl_metadata
        >> normalize_generated_metadata
        >> publish_metadata
        >> publish_files_only
    )
