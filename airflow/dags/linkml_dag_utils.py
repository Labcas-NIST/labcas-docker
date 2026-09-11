"""Shared Airflow tasks for collection-specific LinkML workflows."""

from __future__ import annotations

import os
from typing import Mapping

from airflow.operators.bash import BashOperator


def require_input_files(task_id: str, inputs: Mapping[str, str]) -> BashOperator:
    """Fail early when a runtime-configured metadata input is absent."""
    return BashOperator(
        task_id=task_id,
        bash_command=r"""
set -euo pipefail
for variable in $REQUIRED_INPUT_VARIABLES; do
  path=$(printenv "$variable")
  test -n "$path" || { echo "Missing required setting: $variable" >&2; exit 1; }
  test -s "$path" || { echo "Input is missing or empty for $variable" >&2; exit 1; }
  echo "INPUT_READY variable=$variable"
done
echo 'PIPELINE_MODE=validation PUBLISH_TO_SOLR=disabled_by_default'
""",
        env={
            **inputs,
            "REQUIRED_INPUT_VARIABLES": " ".join(inputs),
        },
    )


def wait_for_validator(task_id: str = "wait_linkml_validator") -> BashOperator:
    """Wait for the shared LinkML validator service."""
    return BashOperator(
        task_id=task_id,
        bash_command=r"""{% raw %}
set -euo pipefail
for attempt in $(seq 1 60); do
  status=$(docker inspect -f '{{.State.Running}}' "$VALIDATOR" 2>/dev/null || echo false)
  if [ "$status" = true ]; then
    echo "VALIDATOR_READY container=$VALIDATOR"
    exit 0
  fi
  echo "Waiting for LinkML validator ($attempt/60)..."
  sleep 2
done
echo 'LinkML validator did not start' >&2
exit 1
{% endraw %}""",
        env={
            "VALIDATOR": os.getenv(
                "LINKML_VALIDATOR_CONTAINER_NAME", "labcas-linkml-validator"
            )
        },
    )


def optional_publish_task(
    default_collection: str,
    task_id: str = "publish_to_solr_if_enabled",
) -> BashOperator:
    """Run the existing LabCAS publisher only after an explicit opt-in."""
    return BashOperator(
        task_id=task_id,
        bash_command=r"""{% raw %}
set -euo pipefail
case "${LABCAS_PUBLISH_ENABLED,,}" in
  1|true|yes|y) ;;
  *)
    echo "PIPELINE_MODE=validation PUBLISH_TO_SOLR=skipped"
    exit 0
    ;;
esac
test -n "$PUBLISH_COLLECTION" || { echo 'PUBLISH_COLLECTION is required' >&2; exit 1; }
test -n "$BASIC_AUTH_USER" || { echo 'BASIC_AUTH_USER is required when publishing' >&2; exit 1; }
test -n "$BASIC_AUTH_PASS" || { echo 'BASIC_AUTH_PASS is required when publishing' >&2; exit 1; }
for attempt in $(seq 1 60); do
  status=$(docker inspect -f '{{.State.Running}}' "$PUBLISH_CONTAINER" 2>/dev/null || echo false)
  [ "$status" = true ] && break
  [ "$attempt" = 60 ] && { echo 'Publish container did not start' >&2; exit 1; }
  sleep 2
done
echo "PIPELINE_MODE=publish PUBLISH_TO_SOLR=enabled collection=$PUBLISH_COLLECTION"
docker exec \
  -e steps="$PUBLISH_STEPS" -e PUBLISH_STEPS="$PUBLISH_STEPS" \
  -e consortium="$PUBLISH_CONSORTIUM" -e PUBLISH_CONSORTIUM="$PUBLISH_CONSORTIUM" \
  -e collection="$PUBLISH_COLLECTION" -e PUBLISH_COLLECTION="$PUBLISH_COLLECTION" \
  -e collection_subset="$PUBLISH_COLLECTION_SUBSET" \
  -e PUBLISH_COLLECTION_SUBSET="$PUBLISH_COLLECTION_SUBSET" \
  -e publish_id="$PUBLISH_ID" -e PUBLISH_ID="$PUBLISH_ID" \
  -e solr="$SOLR_URL" -e SOLR_URL="$SOLR_URL" \
  -e BASIC_AUTH_USER="$BASIC_AUTH_USER" -e BASIC_AUTH_PASS="$BASIC_AUTH_PASS" \
  "$PUBLISH_CONTAINER" python3 /opt/publish/publishing_pipeline.py
{% endraw %}""",
        env={
            "LABCAS_PUBLISH_ENABLED": "{{ dag_run.conf.get('publish_enabled', params.publish_enabled) if dag_run else params.publish_enabled }}",
            "PUBLISH_CONTAINER": os.getenv("PUBLISH_CONTAINER_NAME", "labcas-publish"),
            "PUBLISH_STEPS": os.getenv("PUBLISH_STEPS", "crawl,publish"),
            "PUBLISH_CONSORTIUM": os.getenv("PUBLISH_CONSORTIUM", "NIST"),
            "PUBLISH_COLLECTION": "{{ dag_run.conf.get('publish_collection', params.publish_collection) if dag_run else params.publish_collection }}",
            "PUBLISH_COLLECTION_SUBSET": os.getenv("PUBLISH_COLLECTION_SUBSET", ""),
            "PUBLISH_ID": os.getenv("PUBLISH_ID", ""),
            "SOLR_URL": os.getenv("SOLR_URL", "https://labcas-backend:8984/solr/"),
            "BASIC_AUTH_USER": os.getenv("BASIC_AUTH_USER", ""),
            "BASIC_AUTH_PASS": os.getenv("BASIC_AUTH_PASS", ""),
        },
    )
