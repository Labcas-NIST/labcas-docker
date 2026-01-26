#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Cleanup all Docker resources for this project.

Usage:
  ./cleanup_labcas_docker.sh [--project NAME] [--dry-run] [--force] [--name-pattern REGEX] [--prune-build-cache] [--no-prune-build-cache]

Options:
  --project NAME         Compose project name (default: COMPOSE_PROJECT_NAME or current dir name)
  --dry-run              Show what would be removed without deleting
  --force                Skip confirmation
  --name-pattern REGEX   Also remove resources whose names match REGEX (e.g. 'labcas')
  --prune-build-cache    Prune all Docker build cache (global, not scoped) (default)
  --no-prune-build-cache Skip build cache pruning
USAGE
}

PROJECT=""
DRY_RUN=0
FORCE=0
NAME_PATTERN=""
PRUNE_BUILD_CACHE=1
COMPOSE_FILES=()

while [ $# -gt 0 ]; do
  case "$1" in
    --project)
      PROJECT="$2"; shift 2;;
    --dry-run)
      DRY_RUN=1; shift;;
    --force)
      FORCE=1; shift;;
    --name-pattern)
      NAME_PATTERN="$2"; shift 2;;
    --prune-build-cache)
      PRUNE_BUILD_CACHE=1; shift;;
    --no-prune-build-cache)
      PRUNE_BUILD_CACHE=0; shift;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "Unknown option: $1" >&2; usage; exit 1;;
  esac
done

if [ -z "$PROJECT" ]; then
  PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$(pwd)")}" 
fi

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}

require docker

for f in docker-compose.yml docker-compose.yaml docker-compose.override.yml; do
  [ -f "$f" ] && COMPOSE_FILES+=("$f")
done

compose() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

compose_values() {
  local key="$1"
  [ ${#COMPOSE_FILES[@]} -eq 0 ] && return 0
  awk -v key="$key" '
    {
      line=$0
      sub(/^[[:space:]]*/, "", line)
      if (index(line, key ":") == 1) {
        val=line
        sub(/^[^:]+:[[:space:]]*/, "", val)
        sub(/[[:space:]]+#.*$/, "", val)
        gsub(/^["\047 ]+|["\047 ]+$/, "", val)
        if (val != "") print val
      }
    }' "${COMPOSE_FILES[@]}" | sort -u
}

compose_services() {
  [ ${#COMPOSE_FILES[@]} -eq 0 ] && return 0
  awk '
    /^services:[[:space:]]*$/ {in_services=1; next}
    in_services && /^[^[:space:]]/ {in_services=0}
    in_services && /^  [A-Za-z0-9._-]+:[[:space:]]*$/ {
      line=$0
      sub(/^  /, "", line)
      sub(/:[[:space:]]*$/, "", line)
      print line
    }
  ' "${COMPOSE_FILES[@]}" | sort -u
}

compose_section_names() {
  local section="$1"
  [ ${#COMPOSE_FILES[@]} -eq 0 ] && return 0
  awk -v section="$section" '
    $0 ~ "^" section ":[[:space:]]*$" {in_section=1; next}
    in_section && /^[^[:space:]]/ {in_section=0}
    in_section && /^  [A-Za-z0-9._-]+:[[:space:]]*$/ {
      line=$0
      sub(/^  /, "", line)
      sub(/:[[:space:]]*$/, "", line)
      print line
    }
  ' "${COMPOSE_FILES[@]}" | sort -u
}

run_or_echo() {
  if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

list_by_label() {
  local kind="$1"
  local label="com.docker.compose.project=$PROJECT"
  case "$kind" in
    containers)
      docker ps -a --filter "label=$label" --format '{{.ID}} {{.Names}}';;
    images)
      docker images --filter "label=$label" --format '{{.ID}} {{.Repository}}:{{.Tag}}';;
    volumes)
      docker volume ls --filter "label=$label" --format '{{.Name}}';;
    networks)
      docker network ls --filter "label=$label" --format '{{.Name}}';;
    *)
      return 1;;
  esac
}

list_by_name_pattern() {
  local kind="$1"
  local pattern="$2"
  [ -z "$pattern" ] && return 0
  case "$kind" in
    containers)
      docker ps -a --format '{{.ID}} {{.Names}}' | awk -v pat="$pattern" '$2 ~ pat {print $0}';;
    images)
      docker images --format '{{.ID}} {{.Repository}}:{{.Tag}}' | awk -v pat="$pattern" '$2 ~ pat {print $0}';;
    volumes)
      docker volume ls --format '{{.Name}}' | awk -v pat="$pattern" '$1 ~ pat {print $0}';;
    networks)
      docker network ls --format '{{.Name}}' | awk -v pat="$pattern" '$1 ~ pat {print $0}';;
  esac
}

list_by_exact_container_names() {
  [ $# -eq 0 ] && return 0
  for name in "$@"; do
    docker ps -a --filter "name=^${name}$" --format '{{.ID}} {{.Names}}'
  done
}

list_images_by_service_labels() {
  [ $# -eq 0 ] && return 0
  for service in "$@"; do
    docker images --filter "label=com.docker.compose.service=$service" --format '{{.ID}} {{.Repository}}:{{.Tag}}'
  done
}

list_images_by_references() {
  [ $# -eq 0 ] && return 0
  local image
  for image in "$@"; do
    if [[ "$image" == *":"* || "$image" == *"@"* ]]; then
      docker images --filter "reference=$image" --format '{{.ID}} {{.Repository}}:{{.Tag}}'
    else
      docker images --filter "reference=${image}:*" --format '{{.ID}} {{.Repository}}:{{.Tag}}'
    fi
  done
}

list_by_suffix() {
  local kind="$1"
  shift
  [ $# -eq 0 ] && return 0
  case "$kind" in
    volumes)
      docker volume ls --format '{{.Name}}' | awk -v names="$*" '
        BEGIN{n=split(names,arr," "); for(i=1;i<=n;i++) pats[i]="(^|_)" arr[i] "$"}
        {for(i=1;i<=n;i++) if ($1 ~ pats[i]) {print $1; break}}
      ';;
    networks)
      docker network ls --format '{{.Name}}' | awk -v names="$*" '
        BEGIN{n=split(names,arr," "); for(i=1;i<=n;i++) pats[i]="(^|_)" arr[i] "$"}
        {for(i=1;i<=n;i++) if ($1 ~ pats[i]) {print $1; break}}
      ';;
  esac
}

COMPOSE_CONTAINER_NAMES=()
COMPOSE_IMAGE_NAMES=()
COMPOSE_SERVICE_NAMES=()
COMPOSE_VOLUME_NAMES=()
COMPOSE_NETWORK_NAMES=()

load_compose_targets() {
  COMPOSE_CONTAINER_NAMES=()
  COMPOSE_IMAGE_NAMES=()
  COMPOSE_SERVICE_NAMES=()
  COMPOSE_VOLUME_NAMES=()
  COMPOSE_NETWORK_NAMES=()

  while IFS= read -r line; do
    [ -n "$line" ] && COMPOSE_CONTAINER_NAMES+=("$line")
  done < <(compose_values container_name)

  while IFS= read -r line; do
    [ -n "$line" ] && COMPOSE_IMAGE_NAMES+=("$line")
  done < <(compose_values image)

  while IFS= read -r line; do
    [ -n "$line" ] && COMPOSE_SERVICE_NAMES+=("$line")
  done < <(compose_services)

  while IFS= read -r line; do
    [ -n "$line" ] && COMPOSE_VOLUME_NAMES+=("$line")
  done < <(compose_section_names volumes)

  while IFS= read -r line; do
    [ -n "$line" ] && COMPOSE_NETWORK_NAMES+=("$line")
  done < <(compose_section_names networks)
}

show_targets() {
  echo "Project: $PROJECT"
  echo
  echo "Containers (label match):"
  list_by_label containers || true
  if [ ${#COMPOSE_CONTAINER_NAMES[@]} -gt 0 ]; then
    echo
    echo "Containers (compose names):"
    list_by_exact_container_names "${COMPOSE_CONTAINER_NAMES[@]}" || true
  fi
  if [ -n "$NAME_PATTERN" ]; then
    echo
    echo "Containers (name pattern):"
    list_by_name_pattern containers "$NAME_PATTERN"
  fi
  echo
  echo "Images (label match):"
  list_by_label images || true
  if [ ${#COMPOSE_IMAGE_NAMES[@]} -gt 0 ]; then
    echo
    echo "Images (compose references):"
    list_images_by_references "${COMPOSE_IMAGE_NAMES[@]}" || true
  fi
  if [ ${#COMPOSE_SERVICE_NAMES[@]} -gt 0 ]; then
    echo
    echo "Images (compose service labels):"
    list_images_by_service_labels "${COMPOSE_SERVICE_NAMES[@]}" || true
  fi
  if [ -n "$NAME_PATTERN" ]; then
    echo
    echo "Images (name pattern):"
    list_by_name_pattern images "$NAME_PATTERN"
  fi
  echo
  echo "Volumes (label match):"
  list_by_label volumes || true
  if [ ${#COMPOSE_VOLUME_NAMES[@]} -gt 0 ]; then
    echo
    echo "Volumes (compose names/suffixes):"
    list_by_suffix volumes "${COMPOSE_VOLUME_NAMES[@]}" || true
  fi
  if [ -n "$NAME_PATTERN" ]; then
    echo
    echo "Volumes (name pattern):"
    list_by_name_pattern volumes "$NAME_PATTERN"
  fi
  echo
  echo "Networks (label match):"
  list_by_label networks || true
  if [ ${#COMPOSE_NETWORK_NAMES[@]} -gt 0 ]; then
    echo
    echo "Networks (compose names/suffixes):"
    list_by_suffix networks "${COMPOSE_NETWORK_NAMES[@]}" || true
  fi
  if [ -n "$NAME_PATTERN" ]; then
    echo
    echo "Networks (name pattern):"
    list_by_name_pattern networks "$NAME_PATTERN"
  fi
}

load_compose_targets
show_targets

if [ "$FORCE" != "1" ] && [ "$DRY_RUN" != "1" ]; then
  echo
  read -r -p "Type the project name ($PROJECT) to confirm cleanup: " confirm
  if [ "$confirm" != "$PROJECT" ]; then
    echo "Aborted."; exit 1
  fi
fi

# Best-effort compose down using local compose files (if present)
if [ -f docker-compose.yml ] || [ -f docker-compose.yaml ]; then
  if [ -f docker-compose.override.yml ]; then
    run_or_echo compose -p "$PROJECT" -f docker-compose.yml -f docker-compose.override.yml down --rmi all -v --remove-orphans
  else
    run_or_echo compose -p "$PROJECT" -f docker-compose.yml down --rmi all -v --remove-orphans
  fi
fi

# Label-based cleanup
containers=$(list_by_label containers | awk '{print $1}')
[ -n "$containers" ] && run_or_echo docker rm -f $containers

if [ ${#COMPOSE_CONTAINER_NAMES[@]} -gt 0 ]; then
  containers=$(list_by_exact_container_names "${COMPOSE_CONTAINER_NAMES[@]}" | awk '{print $1}')
  [ -n "$containers" ] && run_or_echo docker rm -f $containers
fi

images=$(list_by_label images | awk '{print $1}')
[ -n "$images" ] && run_or_echo docker rmi -f $images

if [ ${#COMPOSE_IMAGE_NAMES[@]} -gt 0 ]; then
  images=$(list_images_by_references "${COMPOSE_IMAGE_NAMES[@]}" | awk '{print $1}')
  [ -n "$images" ] && run_or_echo docker rmi -f $images
fi

if [ ${#COMPOSE_SERVICE_NAMES[@]} -gt 0 ]; then
  images=$(list_images_by_service_labels "${COMPOSE_SERVICE_NAMES[@]}" | awk '{print $1}')
  [ -n "$images" ] && run_or_echo docker rmi -f $images
fi

volumes=$(list_by_label volumes)
[ -n "$volumes" ] && run_or_echo docker volume rm -f $volumes

networks=$(list_by_label networks)
[ -n "$networks" ] && run_or_echo docker network rm $networks

if [ ${#COMPOSE_VOLUME_NAMES[@]} -gt 0 ]; then
  volumes=$(list_by_suffix volumes "${COMPOSE_VOLUME_NAMES[@]}")
  [ -n "$volumes" ] && run_or_echo docker volume rm -f $volumes
fi

if [ ${#COMPOSE_NETWORK_NAMES[@]} -gt 0 ]; then
  networks=$(list_by_suffix networks "${COMPOSE_NETWORK_NAMES[@]}")
  [ -n "$networks" ] && run_or_echo docker network rm $networks
fi

# Optional name-pattern cleanup (for older runs without compose labels)
if [ -n "$NAME_PATTERN" ]; then
  containers=$(list_by_name_pattern containers "$NAME_PATTERN" | awk '{print $1}')
  [ -n "$containers" ] && run_or_echo docker rm -f $containers

  images=$(list_by_name_pattern images "$NAME_PATTERN" | awk '{print $1}')
  [ -n "$images" ] && run_or_echo docker rmi -f $images

  volumes=$(list_by_name_pattern volumes "$NAME_PATTERN")
  [ -n "$volumes" ] && run_or_echo docker volume rm -f $volumes

  networks=$(list_by_name_pattern networks "$NAME_PATTERN")
  [ -n "$networks" ] && run_or_echo docker network rm $networks
fi

if [ "$PRUNE_BUILD_CACHE" = "1" ]; then
  run_or_echo docker builder prune -f
fi

echo "Cleanup complete."
