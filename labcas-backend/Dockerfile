FROM eclipse-temurin:8-jdk-focal

LABEL maintainer="david.liu@jpl.nasa.gov"
LABEL description="LabCAS Backend service."

ENV LABCAS_HOME=/tmp/labcas
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    wget \
    netcat-openbsd \
    git \
    vim \
    ldap-utils \
    maven && \
    rm -rf /var/lib/apt/lists/*

# Create necessary directories
RUN mkdir -p $LABCAS_HOME/labcas-backend /tmp/labcas/etc

# Clone LabCAS backend repository
RUN git clone https://github.com/EDRN/labcas-backend.git $LABCAS_HOME/labcas-backend

# Build LabCAS backend
WORKDIR $LABCAS_HOME/labcas-backend
RUN mvn clean install

# Setup keystore and certificates
RUN if ! keytool -list -alias solr-ssl -keystore /tmp/labcas/etc/solr-ssl.keystore.p12 -storepass secret 2>/dev/null; then \
    keytool -genkeypair -alias solr-ssl -keyalg RSA -keysize 4096 -validity 720 \
    -keystore /tmp/labcas/etc/solr-ssl.keystore.p12 -storetype PKCS12 -storepass secret \
    -keypass secret -dname "CN=localhost, OU=LabCAS, O=JPL, L=Pasadena, ST=CA, C=USA"; \
    fi

RUN keytool -genkey -alias tomcat -keyalg RSA -keysize 2048 -keystore /etc/ca-certificates/keystore.jks \
    -storepass secret -keypass secret -dname "CN=David, OU=JPL, O=JPL, L=Pasadena, ST=CA, C=US"

# Setup configuration: create symlinks from mounted shared configurations
RUN ln -sf /config/labcas.properties /root/labcas.properties && \
    ln -sf /config/server.xml $LABCAS_HOME/apache-tomcat/conf/server.xml

# Copy keys
RUN mkdir -p /root/certs
COPY hostkey.pem /root/certs/hostkey.pem

# Ensure that the start.sh script exists and is in the correct location
RUN sed -i '/solr start/s/$/ -force/' /tmp/labcas/start.sh

# Make start script executable
RUN chmod +x /tmp/labcas/start.sh

# Expose necessary ports
EXPOSE 8080

COPY init_solr.sh /tmp/labcas/
COPY sample_data /tmp/labcas/sample_data
RUN chmod +x /tmp/labcas/init_solr.sh
# Set entrypoint to start the LabCAS backend services
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
