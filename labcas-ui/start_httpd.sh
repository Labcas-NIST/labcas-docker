#!/bin/bash
# Start httpd in the background
httpd-foreground &
 # Wait for httpd to start
sleep 2
# Detach from the container
# exit 0