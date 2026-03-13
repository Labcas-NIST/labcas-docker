#!/usr/bin/env bash
set -euo pipefail

start_dind() {
  if [ "${DIND_ENABLED:-1}" != "1" ]; then
    return 0
  fi

  echo "Starting Docker-in-Docker..."
  mkdir -p /var/lib/docker
  rm -f /var/run/docker.pid
  dockerd \
    --host=unix:///var/run/docker.sock \
    --data-root=/var/lib/docker \
    --storage-driver=overlay2 \
    > /var/log/dockerd.log 2>&1 &

  for _ in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then
      # Allow airflow user to talk to the inner daemon.
      chmod 666 /var/run/docker.sock || true
      return 0
    fi
    sleep 1
  done

  echo "ERROR: Docker daemon failed to start"
  tail -n 200 /var/log/dockerd.log || true
  exit 1
}

build_publish_image() {
  if [ "${DIND_ENABLED:-1}" != "1" ]; then
    return 0
  fi
  if [ "${BUILD_PUBLISH_IMAGE:-1}" = "0" ]; then
    return 0
  fi

  local image="${PUBLISH_IMAGE:-labcas-docker-clean-publish}"
  if docker image inspect "${image}" >/dev/null 2>&1; then
    echo "Publish image ${image} already present; skipping build."
    return 0
  fi

  if [ ! -d /opt/publish ]; then
    echo "ERROR: /opt/publish not found; cannot build publish image."
    exit 1
  fi

  if [ -d /opt/airflow/publish ]; then
    cp -f /opt/airflow/publish/patch_publishing_pipeline.py /opt/publish/ 2>/dev/null || true
    cp -f /opt/airflow/publish/basic.py.patched /opt/publish/ 2>/dev/null || true
    cp -f /opt/airflow/publish/solr.py.patched /opt/publish/ 2>/dev/null || true
    if [ -f /opt/airflow/publish/labcas-ssl-cert.pem ]; then
      cp -f /opt/airflow/publish/labcas-ssl-cert.pem /opt/publish/
    fi
  fi

  docker build \
    --build-arg PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL:-https://pypi.org/simple}" \
    -t "${image}" \
    -f /opt/airflow/scripts/publish_dind.Dockerfile \
    /opt/publish
}

start_publish_container() {
  if [ "${DIND_ENABLED:-1}" != "1" ]; then
    return 0
  fi
  if [ "${START_PUBLISH_CONTAINER:-1}" = "0" ]; then
    return 0
  fi

  local image="${PUBLISH_IMAGE:-labcas-docker-clean-publish}"
  local container="${PUBLISH_CONTAINER_NAME:-labcas-publish}"
  local data_path="${AIRFLOW_DIND_DATA_PATH:-/data}"
  local metadata_path="${AIRFLOW_DIND_METADATA_PATH:-/metadata}"
  local config_path="${AIRFLOW_DIND_PUBLISH_CONFIG:-/config/publish}"
  local labcas_data_path="${AIRFLOW_DIND_LABCAS_DATA_PATH:-/labcas-data}"

  if ! docker image inspect "${image}" >/dev/null 2>&1; then
    echo "ERROR: Publish image ${image} not found; cannot start ${container}."
    exit 1
  fi

  mkdir -p "${data_path}" "${metadata_path}" "${config_path}" "${labcas_data_path}"

  if docker ps -a --format '{{.Names}}' | grep -qx "${container}"; then
    if docker inspect -f '{{.State.Running}}' "${container}" 2>/dev/null | grep -q "true"; then
      echo "Publish container ${container} already running; skipping start."
      return 0
    fi
    docker rm -f "${container}" >/dev/null
  fi

  docker run -d \
    --name "${container}" \
    --network host \
    -v "${metadata_path}:/mnt/metadata:ro" \
    -v "${data_path}:/data" \
    -v "${labcas_data_path}:/labcas-data" \
    -v "${config_path}:/config/publish:ro" \
    "${image}" >/dev/null
}

build_linkml_validator_image() {
  if [ "${DIND_ENABLED:-1}" != "1" ]; then
    return 0
  fi
  if [ "${BUILD_LINKML_VALIDATOR_IMAGE:-1}" = "0" ]; then
    return 0
  fi

  local image="${LINKML_VALIDATOR_IMAGE:-labcas-docker-clean-linkml-validator}"
  local dockerfile="/opt/airflow/scripts/linkml_validator_dind.Dockerfile"
  local context="/opt/airflow/scripts"

  if docker image inspect "${image}" >/dev/null 2>&1; then
    echo "LinkML validator image ${image} already present; skipping build."
    return 0
  fi

  if [ ! -f "${dockerfile}" ]; then
    echo "ERROR: ${dockerfile} not found; cannot build LinkML validator image."
    exit 1
  fi

  docker build \
    --build-arg LINKML_REPO_URL="${LINKML_REPO_URL:-https://github.com/usnistgov/nist-labcas-linkml.git}" \
    --build-arg LINKML_REPO_REF="${LINKML_REPO_REF:-main}" \
    --build-arg LINKML_GITHUB_TOKEN="${LINKML_GITHUB_TOKEN:-${GITHUB_TOKEN:-}}" \
    -t "${image}" \
    -f "${dockerfile}" \
    "${context}"
}

start_linkml_validator_container() {
  if [ "${DIND_ENABLED:-1}" != "1" ]; then
    return 0
  fi
  if [ "${START_LINKML_VALIDATOR_CONTAINER:-1}" = "0" ]; then
    return 0
  fi

  local image="${LINKML_VALIDATOR_IMAGE:-labcas-docker-clean-linkml-validator}"
  local container="${LINKML_VALIDATOR_CONTAINER_NAME:-labcas-linkml-validator}"
  local data_path="${AIRFLOW_DIND_DATA_PATH:-/data}"
  local metadata_path="${AIRFLOW_DIND_METADATA_PATH:-/metadata}"

  if ! docker image inspect "${image}" >/dev/null 2>&1; then
    echo "ERROR: LinkML validator image ${image} not found; cannot start ${container}."
    exit 1
  fi

  mkdir -p "${data_path}" "${metadata_path}"

  if docker ps -a --format '{{.Names}}' | grep -qx "${container}"; then
    if docker inspect -f '{{.State.Running}}' "${container}" 2>/dev/null | grep -q "true"; then
      echo "LinkML validator container ${container} already running; skipping start."
      return 0
    fi
    docker rm -f "${container}" >/dev/null
  fi

  docker run -d \
    --name "${container}" \
    --network host \
    -v "${data_path}:/data" \
    -v "${metadata_path}:/metadata" \
    "${image}" >/dev/null
}

airflow_cmd() {
  su -p airflow -c "HOME=/home/airflow PATH=/home/airflow/.local/bin:\$PATH airflow $*"
}

start_dind
build_publish_image
start_publish_container
build_linkml_validator_image
start_linkml_validator_container

# Ensure airflow can write logs even though the container runs as root.
chown -R airflow:root /opt/airflow/logs || true

airflow_cmd db upgrade
# create admin user if not exists
if ! airflow_cmd users list | grep -q "^admin\b"; then
  airflow_cmd users create --username admin --password admin --firstname Air --lastname Flow --role Admin --email admin@example.com
fi
# start scheduler in background
su -p airflow -c "HOME=/home/airflow PATH=/home/airflow/.local/bin:\$PATH airflow scheduler" &
# start webserver
exec su -p airflow -c "HOME=/home/airflow PATH=/home/airflow/.local/bin:\$PATH airflow webserver"
