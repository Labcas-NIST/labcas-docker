#!/bin/bash

# Set Solr data directory within the container
SOLR_DATA_DIR=/tmp/labcas/solr/data

# Solr server URL
SOLR_SERVER_URL=https://localhost:8984

# Ensure the Solr data directory exists
mkdir -p $SOLR_DATA_DIR

# Copy JSON files using relative paths
cp /tmp/labcas/sample_data/dataset_solr.json $SOLR_DATA_DIR/
cp /tmp/labcas/sample_data/file_solr.json $SOLR_DATA_DIR/
cp /tmp/labcas/sample_data/collection_solr.json $SOLR_DATA_DIR/

# Function to check if a Solr core is empty
is_core_empty() {
  local core=$1
  local count=$(curl -sk "$SOLR_SERVER_URL/solr/$core/select?q=*:*&rows=0&wt=json" | grep -o '"numFound":[0-9]*' | grep -o '[0-9]*')
  [ "$count" = "0" ]
}

# Only post sample data if the core is empty
declare -A core_json
core_json=( ["datasets"]="dataset_solr.json" ["files"]="file_solr.json" ["collections"]="collection_solr.json" )

for core in datasets files collections; do
  if is_core_empty $core; then
    echo "Core $core is empty, posting sample data..."
    curl -k "$SOLR_SERVER_URL/solr/$core/update?commit=true" --data-binary @$SOLR_DATA_DIR/${core_json[$core]} -H "Content-type:application/json"
  else
    echo "Core $core already has data, skipping sample insert."
  fi
done
