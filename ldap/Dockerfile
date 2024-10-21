FROM bitnami/openldap:latest

LABEL maintainer="david.liu@jpl.nasa.gov"
LABEL description="LDAP service for LabCAS."

# Set environment variables
ENV LDAP_ROOT="dc=labcas,dc=jpl,dc=nasa,dc=gov"
ENV LDAP_ADMIN_USERNAME="admin"
ENV LDAP_ADMIN_PASSWORD="secret"

# Switch to root user to perform privileged operations
USER root

# Create directories in one step
RUN mkdir -p /etc/ldap/ssl /root/certs

RUN openssl req -new -x509 -days 365 -nodes -out /etc/ldap/ssl/ldap-cert.pem -keyout /etc/ldap/ssl/ldap-key.pem -subj "/CN=localhost" && \
    openssl genpkey -algorithm RSA -out /root/certs/hostkey.pem && \
    openssl req -new -x509 -key /root/certs/hostkey.pem -out /root/certs/hostcert.pem -days 365 -subj "/C=US/ST=CA/L=Pasadena/O=JPL/OU=LabCAS/CN=labcas.jpl.nasa.gov"


# Copy ldap setup scripts
COPY ldap /tmp/ldap

# Make ldap setup script executable
RUN chmod +x /tmp/ldap/init_ldap.sh

# Switch back to non-root user
#USER slapd
USER 1001
