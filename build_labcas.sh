#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Variables
IMAGE_NAME="labcas_debug_image_nist"
CONTAINER_NAME="labcas_debug_instance_nist"
LDAP_ADMIN_USERNAME="admin"
LDAP_ADMIN_PASSWORD="secret"
LDAP_ROOT="dc=labcas,dc=jpl,dc=nasa,dc=gov"
HOST_PORT_HTTP=80
HOST_PORT_HTTPS=8444

# Build Docker image without cache
echo "Building Docker image..."
docker build --no-cache -t ${IMAGE_NAME} .

# Run the Docker container in detached mode with environment variables
echo "Running Docker container..."
docker run -d --name ${CONTAINER_NAME} \
    -p ${HOST_PORT_HTTP}:80 \
    -p ${HOST_PORT_HTTPS}:8444 \
    -e LDAP_ADMIN_USERNAME="${LDAP_ADMIN_USERNAME}" \
    -e LDAP_ADMIN_PASSWORD="${LDAP_ADMIN_PASSWORD}" \
    -e LDAP_ROOT="${LDAP_ROOT}" \
    ${IMAGE_NAME}:latest

# Wait for services to spin up
sleep 60

# Initialize LDAP configuration
echo "Initializing LDAP configuration..."
docker exec ${CONTAINER_NAME} bash /tmp/ldap/init_ldap.sh

# Start Apache service inside the container
echo "Starting Apache service..."
docker exec ${CONTAINER_NAME} /usr/sbin/apache2ctl start

# Start LabCAS backend services
echo "Starting LabCAS backend services..."
docker exec ${CONTAINER_NAME} bash -ex /tmp/labcas/start.sh

echo "LabCAS container setup completed successfully."
