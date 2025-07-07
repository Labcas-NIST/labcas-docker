#!/bin/bash
set -e

echo "Sleeping 30 seconds..."
sleep 30

if [ -f "/tmp/labcas/start.sh" ]; then
  echo "Running start.sh..."
  /bin/bash /tmp/labcas/start.sh
else
  echo "start.sh not found."
fi

if [ -f "/tmp/labcas/init_solr.sh" ]; then
  echo "Running init_solr.sh..."
  /bin/bash /tmp/labcas/init_solr.sh
else
  echo "init_solr.sh not found."
fi

echo "Starting tail -f /dev/null to keep container alive."
exec tail -f /dev/null
