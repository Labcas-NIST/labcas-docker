from datetime import datetime
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount
import os


def _required_env(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise RuntimeError(f"Required environment variable {name} is not set inside Airflow. Set it to an absolute host path in docker-compose.yml under the airflow service.")
    return val


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

    parse_task = BashOperator(
        task_id="parse_excel",
        bash_command=(
            "set -euxo pipefail; "
            "ls -al /data || true; "
            "python /opt/airflow/scripts/parse_excel.py /data/raw/Basophile.csv /data/staging/Basophile/Basophile.cfg"
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

    # Build host paths for mounts; fail fast if not provided
    HOST_DATA_PATH = _required_env("HOST_DATA_PATH")
    HOST_METADATA_PATH = _required_env("HOST_METADATA_PATH")
    HOST_LABCAS_DATA = _required_env("HOST_LABCAS_DATA")
    HOST_PUBLISH_CONFIG = _required_env("HOST_PUBLISH_CONFIG")
    HOST_ARCHIVE_PATH = _required_env("HOST_ARCHIVE_PATH")

    # Use a separate host archive directory for the ephemeral run to prevent collisions
    EPHEMERAL_ARCHIVE_HOST = f"{HOST_ARCHIVE_PATH.rstrip('/')}__ephemeral"

    # Credentials and runtime settings
    basic_auth_user = os.getenv("BASIC_AUTH_USER", "dliu")
    basic_auth_pass = os.getenv("BASIC_AUTH_PASS", "secret")

    # Compose network name (default project dir is labcas-docker-clean)
    network_name = os.getenv("COMPOSE_NETWORK_NAME", "labcas-docker-clean_labcas-net")

    publish_ephemeral = DockerOperator(
        task_id="publish_ephemeral",
        image="labcas-docker-clean-publish",
        entrypoint="python3",
        command="/opt/publish/publishing_pipeline.py",
        force_pull=False,
        auto_remove=True,
        mount_tmp_dir=False,
        network_mode=network_name,
        environment={
            # Keep parity with the existing DAG defaults
            "PUBLISH_STEPS": os.getenv("PUBLISH_STEPS", "crawl,publish"),
            "PUBLISH_CONSORTIUM": os.getenv("PUBLISH_CONSORTIUM", "NIST"),
            "PUBLISH_COLLECTION": os.getenv("PUBLISH_COLLECTION", "Basophile"),
            "PUBLISH_COLLECTION_SUBSET": os.getenv("PUBLISH_COLLECTION_SUBSET", ""),
            "PUBLISH_ID": os.getenv("PUBLISH_ID", "ephemeral"),
            # Provide legacy env names some code paths expect
            "steps": os.getenv("PUBLISH_STEPS", "crawl,publish"),
            "consortium": os.getenv("PUBLISH_CONSORTIUM", "NIST"),
            "collection": os.getenv("PUBLISH_COLLECTION", "Basophile"),
            "collection_subset": os.getenv("PUBLISH_COLLECTION_SUBSET", ""),
            "publish_id": os.getenv("PUBLISH_ID", "ephemeral"),
            "BASIC_AUTH_USER": basic_auth_user,
            "BASIC_AUTH_PASS": basic_auth_pass,
            # Backend/Solr endpoints for publish
            "solr": os.getenv("solr", "https://labcas-backend:8984/solr/"),
            "SOLR_URL": os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/"),
        },
        mounts=[
            # Mirror docker-compose publish service mounts
            Mount(source=HOST_METADATA_PATH, target="/mnt/metadata", type="bind", read_only=True),
            Mount(source=HOST_DATA_PATH, target="/data", type="bind", read_only=False),
            Mount(source=HOST_LABCAS_DATA, target="/labcas-data", type="bind", read_only=False),
            # Use isolated archive output for side-by-side comparison
            Mount(source=EPHEMERAL_ARCHIVE_HOST, target="/data/archive", type="bind", read_only=False),
            Mount(source=HOST_PUBLISH_CONFIG, target="/config/publish", type="bind", read_only=True),
        ],
        # Ensure DockerOperator talks to the host Docker via mounted socket from compose
        docker_url="unix://var/run/docker.sock",
        api_version=None,
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

    # Pipeline
    parse_task >> snapshot_before >> publish_ephemeral >> snapshot_after
