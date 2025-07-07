# FROM httpd:latest

# LABEL maintainer="david.liu@jpl.nasa.gov"
# LABEL description="LabCAS UI service."

# # Install git
# RUN apt-get update && \
#     apt-get install -y --no-install-recommends \
#     vim \
#     git && \
#     rm -rf /var/lib/apt/lists/*

# # Clone LabCAS UI repository
# RUN git clone https://github.com/Labcas-NIST/Labcas-ui.git /usr/local/apache2/htdocs/labcas-ui

# # Create configuration directory
# RUN mkdir -p /usr/local/apache2/htdocs/labcas-ui/assets/conf

# # Copy environment configuration
# COPY environment.cfg /usr/local/apache2/htdocs/labcas-ui/assets/conf/
# COPY labcas-proxy.conf /usr/local/apache2/conf/extra/
# RUN echo 'Include conf/extra/labcas-proxy.conf' >> /usr/local/apache2/conf/httpd.conf  

# RUN mkdir -p /app/scripts
# COPY start_httpd.sh /app/scripts/
# RUN chmod +x /app/scripts/start_httpd.sh

# # Create a simple HTML test page
# RUN echo "<html><body><h1>Hello, World2</h1></body></html>" > /usr/local/apache2/htdocs/test.html

# # Expose necessary ports
# EXPOSE 80 443

# # Start Apache server
# CMD ["httpd-foreground"]
# ENTRYPOINT ["/app/scripts/start_httpd.sh"]


FROM labcas-ubuntubase
RUN apt update 
RUN apt install -y apache2 
RUN apt install -y apache2-utils 
RUN apt clean 


# Install git
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    vim \
    git && \
    rm -rf /var/lib/apt/lists/*

# Clone LabCAS UI repository
RUN git clone https://github.com/Labcas-NIST/Labcas-ui.git /var/www/html/labcas-ui

# Create configuration directory
RUN mkdir -p /var/www/html/labcas-ui/assets/conf

#Copy environment configuration
COPY environment.cfg /var/www/html/labcas-ui/assets/conf/
COPY labcas-proxy.conf /etc/apache2/extra/
#RUN echo 'Include /etc/apache2/extra/labcas-proxy.conf' | tee -a /etc/apache2/apache2.conf

# RUN echo "ServerName localhost" | tee -a /etc/apache2/apache2.conf
COPY 000-default.conf /etc/apache2/sites-enabled/000-default.conf
RUN chmod 644 /etc/apache2/sites-enabled/000-default.conf
COPY ports.conf /etc/apache2/ports.conf
RUN chmod 644  /etc/apache2/ports.conf
# COPY apache2.conf /etc/apache2/apache2.conf
# RUN chmod 755  /etc/apache2/apache2.conf
EXPOSE 8081
CMD [ "apache2ctl", "-D", "FOREGROUND"]