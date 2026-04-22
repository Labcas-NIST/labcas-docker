from datetime import datetime
import os

from airflow import DAG
from airflow.operators.bash import BashOperator


with DAG(
    dag_id="cell_expansion_parse_and_publish",
    start_date=datetime(2023, 1, 1),
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
) as dag:
    collection_name = os.getenv("CELL_EXPANSION_COLLECTION", "cell_expansion_collection")
    bundle_dir = os.getenv(
        "CELL_EXPANSION_BUNDLE_DIR", "/data/raw/CellExpansion-04092026_Bundle"
    )
    workbook_path = os.getenv(
        "CELL_EXPANSION_WORKBOOK", "/data/raw/conf/CellLineCrossWalk.xlsx"
    )

    metadata_root = os.getenv("CELL_EXPANSION_METADATA_ROOT", "/metadata")
    archive_root = os.getenv("CELL_EXPANSION_ARCHIVE_ROOT", "/data/archive/nist")
    staging_root = os.getenv(
        "CELL_EXPANSION_STAGING_ROOT", f"/data/staging/{collection_name}"
    )
    collection_mapped_file = os.getenv(
        "CELL_EXPANSION_COLLECTION_MAPPED", f"{staging_root}/collectionlevel.yaml"
    )
    dataset_manifest_file = os.getenv(
        "CELL_EXPANSION_DATASET_MANIFEST", f"{staging_root}/bulk/validation_manifest.json"
    )
    file_manifest_file = os.getenv(
        "CELL_EXPANSION_FILE_MANIFEST",
        f"{staging_root}/files_bulk/file_validation_manifest.json",
    )
    validation_matrix_script = os.getenv(
        "CELL_EXPANSION_LINKML_MATRIX_SCRIPT",
        f"{staging_root}/linkml_validate_matrix.py",
    )
    linkml_log_dir = os.getenv(
        "CELL_EXPANSION_LINKML_LOG_DIR", "/data/logs/airflow/linkml_validation"
    )

    primary_level_map = os.getenv(
        "CELL_EXPANSION_LINKML_PRIMARY_MAP",
        "collection:CollectionLevel,dataset:Datasetlevel,file:FileLevel",
    )
    cross_classes = os.getenv("CELL_EXPANSION_LINKML_CROSS_CLASSES", "ALL_OTHERS")
    cross_levels = os.getenv("CELL_EXPANSION_LINKML_CROSS_LEVELS", "dataset,file")
    strict_primary = os.getenv("CELL_EXPANSION_LINKML_STRICT_PRIMARY", "true")
    strict_cross = os.getenv("CELL_EXPANSION_LINKML_STRICT_CROSS", "false")

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
            "rm -rf \"$CELL_EXPANSION_METADATA_ROOT/$CELL_EXPANSION_COLLECTION\" || true; "
            "rm -rf \"$CELL_EXPANSION_ARCHIVE_ROOT/$CELL_EXPANSION_COLLECTION\" || true; "
            "rm -rf \"/data/generated_metadata/nist/$CELL_EXPANSION_COLLECTION\" || true; "
            "rm -rf \"$CELL_EXPANSION_STAGING_ROOT\" || true; "
            "echo 'Reset complete'"
        ),
        env={
            "CELL_EXPANSION_COLLECTION": collection_name,
            "CELL_EXPANSION_METADATA_ROOT": metadata_root,
            "CELL_EXPANSION_ARCHIVE_ROOT": archive_root,
            "CELL_EXPANSION_STAGING_ROOT": staging_root,
        },
    )

    parse_bundle = BashOperator(
        task_id="parse_bundle",
        bash_command=(
            "set -euxo pipefail; "
            "test -d \"$CELL_EXPANSION_BUNDLE_DIR\"; "
            "test -f \"$CELL_EXPANSION_WORKBOOK\"; "
            "mkdir -p \"$CELL_EXPANSION_METADATA_ROOT\" \"$CELL_EXPANSION_ARCHIVE_ROOT\" \"$CELL_EXPANSION_STAGING_ROOT\"; "
            "python /opt/airflow/scripts/parsers/cell_provenance.py "
            "--bundle-dir \"$CELL_EXPANSION_BUNDLE_DIR\" "
            "--workbook \"$CELL_EXPANSION_WORKBOOK\" "
            "--output-dir \"$CELL_EXPANSION_METADATA_ROOT\" "
            "--staging-dir \"$CELL_EXPANSION_STAGING_ROOT\" "
            "--archive-root \"$CELL_EXPANSION_ARCHIVE_ROOT\" "
            "--collection \"$CELL_EXPANSION_COLLECTION\""
        ),
        env={
            "CELL_EXPANSION_COLLECTION": collection_name,
            "CELL_EXPANSION_BUNDLE_DIR": bundle_dir,
            "CELL_EXPANSION_WORKBOOK": workbook_path,
            "CELL_EXPANSION_METADATA_ROOT": metadata_root,
            "CELL_EXPANSION_ARCHIVE_ROOT": archive_root,
            "CELL_EXPANSION_STAGING_ROOT": staging_root,
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
            "mkdir -p \"$(dirname \"$CELL_EXPANSION_LINKML_MATRIX_SCRIPT\")\"; "
            "cp -f /opt/airflow/scripts/linkml_validate_matrix.py \"$CELL_EXPANSION_LINKML_MATRIX_SCRIPT\"; "
            "chmod a+r \"$CELL_EXPANSION_LINKML_MATRIX_SCRIPT\""
        ),
        env={"CELL_EXPANSION_LINKML_MATRIX_SCRIPT": validation_matrix_script},
    )

    validate_linkml_matrix = BashOperator(
        task_id="validate_linkml_matrix",
        bash_command=(
            "set -euxo pipefail; "
            "mkdir -p \"$CELL_EXPANSION_LINKML_LOG_DIR\"; "
            "RUN_TAG=$(echo \"${AIRFLOW_CTX_DAG_RUN_ID:-manual}\" | tr ':+/' '___'); "
            "LOG_FILE=\"$CELL_EXPANSION_LINKML_LOG_DIR/cell_expansion_linkml_validation_${RUN_TAG}.log\"; "
            "docker exec \"$LINKML_VALIDATOR_CONTAINER_NAME\" "
            "python \"$CELL_EXPANSION_LINKML_MATRIX_SCRIPT\" "
            "--collection-input \"$CELL_EXPANSION_COLLECTION_MAPPED\" "
            "--dataset-manifest \"$CELL_EXPANSION_DATASET_MANIFEST\" "
            "--file-manifest \"$CELL_EXPANSION_FILE_MANIFEST\" "
            "--primary-level-map \"$CELL_EXPANSION_LINKML_PRIMARY_MAP\" "
            "--cross-classes \"$CELL_EXPANSION_LINKML_CROSS_CLASSES\" "
            "--cross-levels \"$CELL_EXPANSION_LINKML_CROSS_LEVELS\" "
            "--strict-primary \"$CELL_EXPANSION_LINKML_STRICT_PRIMARY\" "
            "--strict-cross \"$CELL_EXPANSION_LINKML_STRICT_CROSS\" "
            "2>&1 | tee \"$LOG_FILE\"; "
            "echo \"Wrote LinkML validation log: $LOG_FILE\""
        ),
        env={
            "LINKML_VALIDATOR_CONTAINER_NAME": validator_container,
            "CELL_EXPANSION_LINKML_MATRIX_SCRIPT": validation_matrix_script,
            "CELL_EXPANSION_COLLECTION_MAPPED": collection_mapped_file,
            "CELL_EXPANSION_DATASET_MANIFEST": dataset_manifest_file,
            "CELL_EXPANSION_FILE_MANIFEST": file_manifest_file,
            "CELL_EXPANSION_LINKML_PRIMARY_MAP": primary_level_map,
            "CELL_EXPANSION_LINKML_CROSS_CLASSES": cross_classes,
            "CELL_EXPANSION_LINKML_CROSS_LEVELS": cross_levels,
            "CELL_EXPANSION_LINKML_STRICT_PRIMARY": strict_primary,
            "CELL_EXPANSION_LINKML_STRICT_CROSS": strict_cross,
            "CELL_EXPANSION_LINKML_LOG_DIR": linkml_log_dir,
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

    purge_existing_publish_state = BashOperator(
        task_id="purge_existing_publish_state",
        bash_command=(
            "set -euo pipefail; "
            "if [ \"${PURGE_EXISTING_DATASET_STATE:-true}\" != \"true\" ]; then echo 'Purge disabled'; exit 0; fi; "
            "python - <<'PY'\n"
            "import json\n"
            "import os\n"
            "import shutil\n"
            "import ssl\n"
            "import urllib.request\n"
            "from pathlib import Path\n"
            "\n"
            "manifest = json.loads(Path(os.environ['CELL_EXPANSION_DATASET_MANIFEST']).read_text())\n"
            "if not manifest:\n"
            "    raise SystemExit('Dataset manifest is empty')\n"
            "dataset = manifest[0]\n"
            "dataset_id = dataset['dataset_id']\n"
            "dataset_key = dataset['dataset_key']\n"
            "collection = os.environ['CELL_EXPANSION_COLLECTION']\n"
            "\n"
            "for path in [\n"
            "    Path('/data/generated_metadata/nist') / collection / dataset_key,\n"
            "    Path('/data/generated_metadata') / collection / dataset_key,\n"
            "]:\n"
            "    if path.exists():\n"
            "        shutil.rmtree(path)\n"
            "        print(f'removed {path}')\n"
            "\n"
            "solr = os.environ['SOLR_URL'].rstrip('/')\n"
            "ctx = ssl._create_unverified_context()\n"
            "queries = {\n"
            "    'files': f'DatasetId:\"{dataset_id}\"',\n"
            "    'datasets': f'id:\"{dataset_id}\"',\n"
            "}\n"
            "for core, query in queries.items():\n"
            "    url = f'{solr}/{core}/update?commit=true'\n"
            "    payload = json.dumps({'delete': {'query': query}}).encode('utf-8')\n"
            "    req = urllib.request.Request(\n"
            "        url,\n"
            "        data=payload,\n"
            "        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},\n"
            "    )\n"
            "    with urllib.request.urlopen(req, context=ctx) as resp:\n"
            "        print(core, query, resp.read().decode())\n"
            "PY"
        ),
        env={
            "CELL_EXPANSION_COLLECTION": collection_name,
            "CELL_EXPANSION_DATASET_MANIFEST": dataset_manifest_file,
            "PURGE_EXISTING_DATASET_STATE": os.getenv(
                "PURGE_EXISTING_DATASET_STATE", "true"
            ),
            "SOLR_URL": os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/"),
        },
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
        >> parse_bundle
        >> wait_validator_container
        >> stage_validation_matrix_script
        >> validate_linkml_matrix
        >> wait_publish_container
        >> purge_existing_publish_state
        >> crawl_metadata
        >> normalize_generated_metadata
        >> publish_metadata
        >> publish_files_only
    )
