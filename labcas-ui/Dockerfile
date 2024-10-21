FROM httpd:latest

LABEL maintainer="david.liu@jpl.nasa.gov"
LABEL description="LabCAS UI service."

# Install git
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git && \
    rm -rf /var/lib/apt/lists/*

# Clone LabCAS UI repository
RUN git clone https://github.com/Labcas-NIST/Labcas-ui.git /usr/local/apache2/htdocs/labcas-ui

# Create configuration directory
RUN mkdir -p /usr/local/apache2/htdocs/labcas-ui/assets/conf

# Copy environment configuration
COPY environment.cfg /usr/local/apache2/htdocs/labcas-ui/assets/conf/

# Create a simple HTML test page
RUN echo "<html><body><h1>Hello, World2</h1></body></html>" > /usr/local/apache2/htdocs/test.html

# Expose necessary ports
EXPOSE 80 443

# Start Apache server
CMD ["httpd-foreground"]
