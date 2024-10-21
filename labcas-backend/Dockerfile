FROM openjdk:8-jdk

LABEL maintainer="david.liu@jpl.nasa.gov"
LABEL description="LabCAS Backend service."

ENV LABCAS_HOME=/tmp/labcas
#ENV JAVA_HOME=/usr/local/jdk8u422-b05
#ENV PATH="${JAVA_HOME}/bin:${PATH}"
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    wget \
    netcat-openbsd \
    git \
    maven && \
    rm -rf /var/lib/apt/lists/*

# Install specific OpenJDK version if necessary
# (Include your JDK installation steps if needed)

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

# Copy configuration files
COPY labcas.properties /root/
COPY server.xml $LABCAS_HOME/apache-tomcat/conf/

# Modify start script if necessary
# Ensure that the start.sh script exists and is in the correct location
RUN sed -i '/solr start/s/$/ -force/' /tmp/labcas/start.sh

# Make start script executable
RUN chmod +x /tmp/labcas/start.sh

# Expose necessary ports
EXPOSE 8080

# Set entrypoint to start the LabCAS backend services
CMD ["/tmp/labcas/start.sh"]
