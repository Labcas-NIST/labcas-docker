#!/usr/bin/env bash
set -euo pipefail

# init.sh — Rebuild, deploy, trigger, and verify the NIST flow cytometry pipeline
#
# Environment overrides (optional):
#   SKIP_BUILD=1                # skip docker compose build
#   PUBLISH_CONSORTIUM=NIST     # consortium (default: NIST)
#   PUBLISH_COLLECTION=fcs_interlab_study
#   PUBLISH_STEPS=crawl,publish
#   BASIC_AUTH_USER=dliu        # Data Access API auth
#   BASIC_AUTH_PASS=secret
#   TIMEOUT_SECONDS=900         # monitor timeout (default 15m)
#
# Usage:
#   bash init.sh

CONSORTIUM=${PUBLISH_CONSORTIUM:-NIST}
COLLECTION=${PUBLISH_COLLECTION:-fcs_interlab_study}
STEPS=${PUBLISH_STEPS:-crawl,publish}
AUTH_USER=${BASIC_AUTH_USER:-dliu}
AUTH_PASS=${BASIC_AUTH_PASS:-secret}
TIMEOUT=${TIMEOUT_SECONDS:-3600}
BUILD_CACHE_SUMMARY=""
BUILD_USED_NO_CACHE=0
QUEUED_SEEN=0

# Predictable run id so we can monitor only the run we trigger (avoids scheduled runs)
NOW_UTC=$(date -u +%Y-%m-%dT%H:%M:%S%z)
RUN_ID="manual__${NOW_UTC}"
E_NOW_UTC=$(date -u +%Y-%m-%dT%H:%M:%S%z)
E_RUN_ID="manual__ephemeral__${E_NOW_UTC}"
M_NOW_UTC=$(date -u +%Y-%m-%dT%H:%M:%S%z)
M_RUN_ID="manual__microbial__${M_NOW_UTC}"

compose() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}

check_build_cache() {
  local total reclaimable
  if ! docker buildx du >/tmp/buildx_du.txt 2>/dev/null; then
    BUILD_CACHE_SUMMARY="Build cache check skipped (buildx not available)"
    return 0
  fi
  total=$(awk '/^Total:/ {print $2}' /tmp/buildx_du.txt)
  reclaimable=$(awk '/^Reclaimable:/ {print $2}' /tmp/buildx_du.txt)
  if [ -n "$total" ] && [ "$total" != "0B" ] && [ "$total" != "0" ]; then
    if [ "$BUILD_USED_NO_CACHE" = "1" ]; then
      BUILD_CACHE_SUMMARY="Build cache present (global): Total=$total, Reclaimable=$reclaimable. This run used --no-cache; cache may be from other builds."
    else
      BUILD_CACHE_SUMMARY="Build cache present (global): Total=$total, Reclaimable=$reclaimable. Tip: use 'docker compose build --no-cache labcas-ui' if you need the latest UI sources."
    fi
  else
    BUILD_CACHE_SUMMARY="Build cache empty: Total=${total:-0B}, Reclaimable=${reclaimable:-0B}"
  fi
}

print_build_cache_summary() {
  if [ -n "$BUILD_CACHE_SUMMARY" ]; then
    echo "$BUILD_CACHE_SUMMARY"
  fi
}

wait_airflow() {
  for i in {1..60}; do
    if docker exec airflow bash -lc "airflow version" >/dev/null 2>&1; then return 0; fi
    echo "Waiting for Airflow CLI... ($i)"; sleep 5;
  done
  echo "Airflow CLI was not ready in time" >&2; return 1
}

wait_solr() {
  for i in {1..60}; do
    if curl -skf https://localhost:8984/solr/admin/info/system >/dev/null; then echo "Solr is ready"; return 0; fi
    echo "Waiting for Solr... ($i)"; sleep 5;
  done
  echo "Solr did not become ready" >&2; return 1
}

wait_publish() {
  for i in {1..30}; do
    status=$(docker inspect -f '{{.State.Running}}' labcas-publish 2>/dev/null || echo 'false')
    [ "$status" = "true" ] && return 0
    echo "Waiting for labcas-publish... ($i)"; sleep 3;
  done
  echo "labcas-publish container not running" >&2; return 1
}

trigger_dag() {
  docker exec airflow bash -lc "airflow dags unpause nist_parse_and_publish || true"
  docker exec airflow bash -lc "airflow dags trigger -r '$RUN_ID' nist_parse_and_publish" | sed -n '1,3p'
}

trigger_microbial_dag() {
  docker exec airflow bash -lc "airflow dags unpause microbial_strain_parse_and_publish || true"
  docker exec airflow bash -lc "airflow dags trigger -r '$M_RUN_ID' microbial_strain_parse_and_publish" | sed -n '1,3p'
}

latest_run_id() {
  # Prefer the specific manual run id we just triggered; fall back to most recent manual run
  if [ -n "${RUN_ID:-}" ]; then echo "$RUN_ID"; return 0; fi
  docker exec airflow bash -lc "airflow dags list-runs -d nist_parse_and_publish" \
    | awk -F '|' 'NR>2 && $2 ~ /manual__/ {gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2; exit 0}'
}

run_execution_date() {
  local dag_id="$1"
  local run_id="$2"
  docker exec airflow bash -lc "airflow dags list-runs -d $dag_id --output json" \
    | python3 -c 'import json,sys; run_id=sys.argv[1]; runs=json.load(sys.stdin); ed=[r.get("execution_date","") for r in runs if r.get("run_id")==run_id]; print(ed[0] if ed else ""); sys.exit(0 if ed else 1)' "$run_id"
}

run_info() {
  local dag_id="$1"
  local run_id="$2"
  docker exec airflow bash -lc "airflow dags list-runs -d $dag_id --output json" \
    | python3 -c 'import json,sys; run_id=sys.argv[1]; runs=json.load(sys.stdin); m=[r for r in runs if r.get("run_id")==run_id]; \
print("{}|{}".format(m[0].get("execution_date",""), m[0].get("state","")) if m else ""); sys.exit(0 if m else 1)' "$run_id"
}

print_queue_diagnostics() {
  local dag_id="$1"
  echo "Queued diagnostics for $dag_id:"
  docker exec airflow bash -lc "airflow dags list-runs -d $dag_id --output json" \
    | python3 -c 'import json,sys; runs=json.load(sys.stdin); \
running=[r for r in runs if r.get("state")=="running"]; \
queued=[r for r in runs if r.get("state")=="queued"]; \
print("Active running runs:"); \
print("\\n".join(["  {0} | {1} | {2}".format(r.get("run_id"), r.get("execution_date"), r.get("start_date")) for r in running]) or "  (none)"); \
print("Queued runs:"); \
print("\\n".join(["  {0} | {1}".format(r.get("run_id"), r.get("execution_date")) for r in queued]) or "  (none)")' || true
  if docker exec airflow bash -lc "command -v ps >/dev/null 2>&1"; then
    docker exec airflow bash -lc "ps -ef | grep -E 'airflow (scheduler|webserver|triggerer)' | grep -v grep || true"
  else
    echo "Scheduler process check skipped (ps not available)"
  fi
  if ! docker exec airflow bash -lc "airflow jobs list --job-type SchedulerJob --limit 5" >/dev/null 2>&1; then
    echo "Scheduler job list not supported; using airflow jobs check:"
    docker exec airflow bash -lc "airflow jobs check --job-type SchedulerJob || true"
  else
    docker exec airflow bash -lc "airflow jobs list --job-type SchedulerJob --limit 5 || true"
  fi
}

monitor_run() {
  local run_id="$1"
  local end=$((SECONDS + TIMEOUT))
  local execution_date=""
  local run_state=""
  local queued_checks=0
  while [ $SECONDS -lt $end ]; do
    local states
    local info
    info=$(run_info nist_parse_and_publish "$run_id" || true)
    if [ -n "$info" ]; then
      execution_date="${info%%|*}"
      run_state="${info#*|}"
    fi
    if [ -n "$run_state" ]; then
      echo "DAG run state: $run_state"
      if [ "$run_state" = "success" ]; then return 0; fi
      if [ "$run_state" = "failed" ]; then return 1; fi
      if [ "$run_state" = "queued" ]; then
        QUEUED_SEEN=1
        queued_checks=$((queued_checks + 1))
        if [ "$queued_checks" -eq 3 ] || [ $((queued_checks % 6)) -eq 0 ]; then
          print_queue_diagnostics nist_parse_and_publish
        fi
        sleep 10; continue;
      fi
    fi
    queued_checks=0
    if [ -z "$execution_date" ]; then
      execution_date=$(run_execution_date nist_parse_and_publish "$run_id" || true)
    fi
    if [ -n "$execution_date" ]; then
      states=$(docker exec airflow bash -lc "airflow tasks states-for-dag-run nist_parse_and_publish $execution_date")
    else
      states=$(docker exec airflow bash -lc "airflow tasks states-for-dag-run nist_parse_and_publish $run_id")
    fi
    echo "$states" | sed -n '1,8p'
    if echo "$states" | grep -Eq "publish_metadata\s+\|\s+success"; then
      echo "publish done"; return 0
    fi
    if echo "$states" | grep -Eq "publish_metadata\s+\|\s+failed"; then
      echo "publish failed"; return 1
    fi
    sleep 10
  done
  echo "Timed out waiting for publish to complete" >&2
  print_queue_diagnostics nist_parse_and_publish
  return 2
}

monitor_ephemeral() {
  local run_id="$1"
  local end=$((SECONDS + TIMEOUT))
  local execution_date=""
  local run_state=""
  local queued_checks=0
  while [ $SECONDS -lt $end ]; do
    local states
    local info
    info=$(run_info parse_and_publish_ephemeral "$run_id" || true)
    if [ -n "$info" ]; then
      execution_date="${info%%|*}"
      run_state="${info#*|}"
    fi
    if [ -n "$run_state" ]; then
      echo "DAG run state: $run_state"
      if [ "$run_state" = "success" ]; then return 0; fi
      if [ "$run_state" = "failed" ]; then return 1; fi
      if [ "$run_state" = "queued" ]; then
        QUEUED_SEEN=1
        queued_checks=$((queued_checks + 1))
        if [ "$queued_checks" -eq 3 ] || [ $((queued_checks % 6)) -eq 0 ]; then
          print_queue_diagnostics parse_and_publish_ephemeral
        fi
        sleep 10; continue;
      fi
    fi
    queued_checks=0
    if [ -z "$execution_date" ]; then
      execution_date=$(run_execution_date parse_and_publish_ephemeral "$run_id" || true)
    fi
    if [ -n "$execution_date" ]; then
      states=$(docker exec airflow bash -lc "airflow tasks states-for-dag-run parse_and_publish_ephemeral $execution_date")
    else
      states=$(docker exec airflow bash -lc "airflow tasks states-for-dag-run parse_and_publish_ephemeral $run_id")
    fi
    echo "$states" | sed -n '1,10p'
    if echo "$states" | grep -Eq "publish_ephemeral\s+\|\s+success"; then
      echo "ephemeral publish done"; return 0
    fi
    if echo "$states" | grep -Eq "publish_ephemeral\s+\|\s+failed"; then
      echo "ephemeral publish failed"; return 1
    fi
    sleep 10
  done
  echo "Timed out waiting for ephemeral publish to complete" >&2
  print_queue_diagnostics parse_and_publish_ephemeral
  return 2
}

monitor_microbial() {
  local run_id="$1"
  local end=$((SECONDS + TIMEOUT))
  local execution_date=""
  local run_state=""
  local queued_checks=0
  while [ $SECONDS -lt $end ]; do
    local states
    local info
    info=$(run_info microbial_strain_parse_and_publish "$run_id" || true)
    if [ -n "$info" ]; then
      execution_date="${info%%|*}"
      run_state="${info#*|}"
    fi
    if [ -n "$run_state" ]; then
      echo "DAG run state: $run_state"
      if [ "$run_state" = "success" ]; then return 0; fi
      if [ "$run_state" = "failed" ]; then return 1; fi
      if [ "$run_state" = "queued" ]; then
        QUEUED_SEEN=1
        queued_checks=$((queued_checks + 1))
        if [ "$queued_checks" -eq 3 ] || [ $((queued_checks % 6)) -eq 0 ]; then
          print_queue_diagnostics microbial_strain_parse_and_publish
        fi
        sleep 10; continue;
      fi
    fi
    queued_checks=0
    if [ -z "$execution_date" ]; then
      execution_date=$(run_execution_date microbial_strain_parse_and_publish "$run_id" || true)
    fi
    if [ -n "$execution_date" ]; then
      states=$(docker exec airflow bash -lc "airflow tasks states-for-dag-run microbial_strain_parse_and_publish $execution_date")
    else
      states=$(docker exec airflow bash -lc "airflow tasks states-for-dag-run microbial_strain_parse_and_publish $run_id")
    fi
    echo "$states" | sed -n '1,8p'
    if echo "$states" | grep -Eq "publish_metadata\s+\|\s+success"; then
      echo "microbial publish done"; return 0
    fi
    if echo "$states" | grep -Eq "publish_metadata\s+\|\s+failed"; then
      echo "microbial publish failed"; return 1
    fi
    sleep 10
  done
  echo "Timed out waiting for microbial publish to complete" >&2
  print_queue_diagnostics microbial_strain_parse_and_publish
  return 2
}

print_counts() {
  local auth
  auth=$(printf '%s:%s' "$AUTH_USER" "$AUTH_PASS" | base64)
  echo '--- Direct Solr ---'
  echo -n 'files (all):          '; curl -sk 'https://localhost:8984/solr/files/select?q=*:*&rows=0&wt=json' || true; echo
  echo -n "files (collection):   "; curl -sk "https://localhost:8984/solr/files/select?q=CollectionId:%22$COLLECTION%22&rows=0&wt=json" || true; echo
  echo -n 'files (WG1):          '; curl -sk "https://localhost:8984/solr/files/select?q=DatasetId:$COLLECTION/WG1-001*&rows=0&wt=json" || true; echo
  echo -n 'datasets (collection):'; curl -sk "https://localhost:8984/solr/datasets/select?q=CollectionId:%22$COLLECTION%22&rows=0&wt=json" || true; echo
  echo '--- Data Access API (auth required) ---'
  echo -n "files (collection):   "; curl -sk -H "Authorization: Basic $auth" "https://localhost/labcas-backend//data-access-api/files/select?q=CollectionId:%22$COLLECTION%22&rows=0&wt=json" || true; echo
}

main() {
  require docker
  require curl
  mkdir -p metadata data/archive data/logs || true

  check_build_cache

  if [ "${SKIP_BUILD:-0}" != "1" ]; then
    BUILD_USED_NO_CACHE=1
    echo "Building images..."
    compose build --pull --no-cache publish airflow labcas-backend labcas-ui labcas-proxy
  else
    echo "Skipping image build (SKIP_BUILD=$SKIP_BUILD)"
  fi

  echo "Starting services..."
  compose up -d postgres ldap labcas-backend publish airflow labcas-ui labcas-proxy

  wait_airflow
  wait_solr
  wait_publish

  echo "Triggering DAG nist_parse_and_publish..."
  trigger_dag
  sleep 3
  run_id=$(latest_run_id)
  echo "Monitoring run: $run_id"
  if monitor_run "$run_id"; then
    echo "Triggering DAG microbial_strain_parse_and_publish..."
    trigger_microbial_dag
    sleep 3
    echo "Monitoring microbial run: $M_RUN_ID"
    if ! monitor_microbial "$M_RUN_ID"; then
      logdir="airflow/logs/dag_id=microbial_strain_parse_and_publish/run_id=${M_RUN_ID}/task_id=publish_metadata"
      echo "Microbial publish failed. Log tail (if available):"
      [ -f "$logdir/attempt=1.log" ] && tail -n 200 "$logdir/attempt=1.log" || true
      print_queue_diagnostics microbial_strain_parse_and_publish
      print_build_cache_summary
      exit 1
    fi
    print_counts
    echo "Done."
    if [ "${RUN_EPHEMERAL:-0}" = "1" ]; then
      echo "Triggering ephemeral DAG parse_and_publish_ephemeral..."
      docker exec airflow bash -lc "airflow dags unpause parse_and_publish_ephemeral || true"
      docker exec airflow bash -lc "airflow dags trigger -r '$E_RUN_ID' parse_and_publish_ephemeral" | sed -n '1,3p'
      echo "Monitoring ephemeral run: $E_RUN_ID"
      monitor_ephemeral "$E_RUN_ID" || true
    fi
    print_queue_diagnostics nist_parse_and_publish
    print_build_cache_summary
    exit 0
  else
    # Print failure context
    logdir="airflow/logs/dag_id=nist_parse_and_publish/run_id=${run_id}/task_id=publish_metadata"
    echo "Publish failed. Log tail (if available):"
    [ -f "$logdir/attempt=1.log" ] && tail -n 200 "$logdir/attempt=1.log" || true
    print_counts
    print_queue_diagnostics nist_parse_and_publish
    print_build_cache_summary
    exit 1
  fi
}

main "$@"
