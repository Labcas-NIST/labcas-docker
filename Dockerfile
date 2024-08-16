# Base image
FROM bitnami/openldap:latest

# Metadata
LABEL maintainer="david.liu@jpl.nasa.gov"
LABEL description="Dockerfile for LabCAS setup."

# Set environment variables
ENV LDAP_ROOT="dc=labcas,dc=jpl,dc=nasa,dc=gov"
ENV LDAP_ADMIN_PASSWORD="secret"
ENV DEBIAN_FRONTEND=noninteractive
ENV LABCAS_HOME=/tmp/labcas
ENV JAVA_HOME=/usr/local/jdk8u422-b05
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Switch to root user
USER root

# Update and install all dependencies in one step
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    software-properties-common \
    wget \
    netcat-traditional \
    git \
    apache2 \
    maven && \
    rm -rf /var/lib/apt/lists/*

# Install OpenJDK and set environment variables
COPY dependencies/OpenJDK8U-jdk_x64_linux_hotspot_8u422b05.tar.gz /tmp/
RUN tar -xzf /tmp/OpenJDK8U-jdk_x64_linux_hotspot_8u422b05.tar.gz -C /usr/local && \
    rm /tmp/OpenJDK8U-jdk_x64_linux_hotspot_8u422b05.tar.gz

# Create directories in one step
RUN mkdir -p $LABCAS_HOME/labcas-backend /tmp/labcas/etc /etc/ldap/ssl /root/certs

# Clone LabCAS backend repository
RUN git clone https://github.com/EDRN/labcas-backend.git $LABCAS_HOME/labcas-backend
WORKDIR $LABCAS_HOME/labcas-backend
RUN mvn clean install

# Setup keystore and certificates
RUN if ! keytool -list -alias solr-ssl -keystore /tmp/labcas/etc/solr-ssl.keystore.p12 -storepass secret 2>/dev/null; then \
    keytool -genkeypair -alias solr-ssl -keyalg RSA -keysize 4096 -validity 720 \
    -keystore /tmp/labcas/etc/solr-ssl.keystore.p12 -storetype PKCS12 -storepass secret \
    -keypass secret -dname "CN=localhost, OU=LabCAS, O=JPL, L=Pasadena, ST=CA, C=USA"; \
    fi && \
    if ! keytool -list -alias tomcat -keystore /etc/ca-certificates/keystore.jks -storepass secret 2>/dev/null; then \
    keytool -genkey -alias tomcat -keyalg RSA -keysize 2048 -keystore /etc/ca-certificates/keystore.jks \
    -storepass secret -keypass secret -dname "CN=David, OU=JPL, O=JPL, L=Pasadena, ST=CA, C=US"; \
    fi && \
    openssl req -new -x509 -days 365 -nodes -out /etc/ldap/ssl/ldap-cert.pem -keyout /etc/ldap/ssl/ldap-key.pem -subj "/CN=localhost" && \
    openssl genpkey -algorithm RSA -out /root/certs/hostkey.pem && \
    openssl req -new -x509 -key /root/certs/hostkey.pem -out /root/certs/hostcert.pem -days 365 -subj "/C=US/ST=CA/L=Pasadena/O=JPL/OU=LabCAS/CN=labcas.jpl.nasa.gov"

# Ldap setup scripts
COPY ldap /tmp/ldap

# Copy and set up configuration files
COPY backend/labcas.properties /root/
COPY tomcat/server.xml $LABCAS_HOME/apache-tomcat/conf/

# Set up LabCAS UI
COPY ui /tmp/ui

RUN git clone https://github.com/Labcas-NIST/Labcas-ui.git /var/www/html/labcas-ui && \                                                                                                                                                        
    mkdir -p /var/www/html/labcas-ui/assets/conf && \
    mv /tmp/ui/environment.cfg /var/www/html/labcas-ui/assets/conf/environment.cfg

# Create a simple HTML test page
RUN echo "<html><body><h1>Hello, World2</h1></body></html>" > /var/www/html/test.html

# Final setup
RUN sed -i '/solr start/s/$/ -force/' /tmp/labcas/start.sh

# Make necessary scripts executable
RUN chmod +x /tmp/ldap/init_ldap.sh /tmp/labcas/start.sh

# Expose necessary ports (if needed)
EXPOSE 80 443

# Set default command
CMD ["/tmp/labcas/start.sh"]
