#
# Base (Ubuntu) Linux Dockerfile
#
# This provides a base image supporting non-java components.  It
# provides these key software prerequisites:
#   + python 3.10
#   + nginx web server (with support for HTTPS)
#

# Ubuntu 22.04  
# 
FROM ubuntu:jammy
ENV DEBIAN_FRONTEND noninteractive
# Install common software.
RUN \
  sed -i 's/# \(.*multiverse$\)/\1/g' /etc/apt/sources.list && \
  apt-get update && \
  apt-get -y upgrade && \
  apt-get install -y build-essential software-properties-common locales \
                     ca-certificates numactl libxml2-dev libxmlsec1-dev \
                     pkg-config python3 python3-pip python3-dev python3-yaml \
                     python-is-python3 byobu curl git htop man unzip vim wget \
                     less nginx libpcre3 libpcre3-dev &&  \
  rm -rf /var/lib/apt/lists/*
RUN locale-gen en_US; locale-gen en_US.UTF-8




####

RUN ARCH=$(uname -m) && \
    # Install standard dependencies that work on all architectures
    pip install annotated-types anyio certifi charset-normalizer click colorama \
    dnspython exceptiongroup fastapi h11 idna pydantic pydantic-settings \
    pydantic_core pymongo python-dotenv requests sniffio starlette \
    typing_extensions urllib3 uvicorn isodate pyjwt && \
    # Handle xmlsec and python3-saml differently based on architecture
    if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
        echo "Detected ARM64 architecture. Using alternative approach for xmlsec." && \
        # Try binary install first
        pip install --only-binary :all: xmlsec || \
        # If that fails, try with build isolation disabled
        pip install --no-build-isolation xmlsec || \
        # If that still fails, skip it but install python3-saml without dependencies
        (echo "xmlsec installation failed on ARM64, continuing without it" && \
         pip install python3-saml --no-deps); \
    else \
        echo "Using standard installation on $ARCH" && \
        pip install xmlsec python3-saml; \
    fi

# uwsgi
# 
# First ensure we don't run into library incompatibilities: rebuild 
# lxml and xmlsec against the libxml2 installed above
#
RUN pip install --no-cache-dir --force-reinstall lxml 
ENV UWSGI_VERS=2.0.28
RUN curl -L -o /tmp/uwsgi.tar.gz \
         https://github.com/unbit/uwsgi/archive/refs/tags/$UWSGI_VERS.tar.gz
RUN cd /usr/local/src && tar xzf /tmp/uwsgi.tar.gz && \
    ln -s uwsgi-$UWSGI_VERS uwsgi && mkdir -p /usr/local/lib/uwsgi/plugins && \
    echo "plugin_dir = /usr/local/lib/uwsgi/plugins" >> uwsgi/buildconf/default.ini
RUN pip install /usr/local/src/uwsgi

# for apps that may expect to use "--plugin python3" or "--plugin python"
RUN PYTHON=python3 uwsgi --build-plugin "/usr/local/src/uwsgi/plugins/python python3" && \
    mv python3_plugin.so /usr/local/lib/uwsgi/plugins/python3_plugin.so && \
    chmod 644 /usr/local/lib/uwsgi/plugins/python3_plugin.so
RUN cd /usr/local/lib/uwsgi/plugins && ln -s python3_plugin.so python_plugin.so
# RUN update-alternatives --install /usr/lib/uwsgi/plugins/python_plugin.so \
#     python_plugin.so /usr/lib/uwsgi/plugins/python3_plugin.so 1
RUN pip install uwsgitop

COPY cacerts/README.md cacerts/*.crt /usr/local/share/ca-certificates/
RUN update-ca-certificates
ENV REQUESTS_CA_BUNDLE /etc/ssl/certs/ca-certificates.crt

RUN pip install requests 
ENV PYTHONIOENCODING utf8

# Create the oarop user that runtime systems should run on by default.
# This user's UID must be set to 1000 to ensure alignment with the oarop
# user on the host system.  
#
RUN sed --in-place -e '/CREATE_MAIL_SPOOL/ s/=yes/=no/' /etc/default/useradd
ARG opuser=oarop
ARG opuid=1000
RUN groupadd --gid $opuid $opuser && \
    useradd -m --comment "OAR Operations" --shell /bin/bash \
            --gid $opuid --uid $opuid $opuser

ENV OAR_OP_USER $opuser

RUN mkdir ~/gnupg && chmod go-rwx ~/gnupg && echo "disable-ipv6" >> ~/gnupg/dirmngr.conf

# Copy default webpage
RUN rm /var/www/html/index.nginx-debian.html && \
    rm /etc/nginx/sites-enabled/*
COPY html/index.html /var/www/html/index.html
COPY html/robots.txt /var/www/html/robots.txt
RUN chmod a+r /var/www/html/robots.txt /var/www/html/index.html

# Copy in CA certs
COPY certs/digicert-intermediate.cer /etc/ssl/certs/digicert-intermediate.pem
COPY certs/dhparam.pem /etc/ssl/certs/dhparam.pem
# COPY certs/NISTIssuingCA01.chain.pem /etc/ssl/certs/NISTIssuingCA01.chain.pem
# COPY certs/NISTIssuingCA03.chain.pem /etc/ssl/certs/NISTIssuingCA03.chain.pem
COPY certs/OAR-DevOnly-SiteCA.chain.cert.pem /etc/ssl/certs/OAR-DevOnly-SiteCA.chain.pem
# RUN cat /etc/ssl/certs/NISTIssuingCA01.chain.pem    \
#         /etc/ssl/certs/NISTIssuingCA03.chain.pem    \
RUN cat  /etc/ssl/certs/OAR-DevOnly-SiteCA.chain.pem \
        /etc/ssl/certs/digicert-intermediate.pem    \
        >> /etc/ssl/certs/dev-test.chain.pem
RUN chgrp oarop /etc/ssl/private && chmod g+rx /etc/ssl/private

COPY nginx.conf /etc/nginx/nginx.conf
RUN chmod a+r /etc/nginx/nginx.conf
# The child image will copy over the default.conf

ARG cachain=dev-test

RUN if [ -s /etc/ssl/certs/$cachain.chain.pem ]; then        \
     cat /etc/ssl/certs/$cachain.chain.pem >>                \
         /etc/ssl/certs/ca-certificates.crt;                 \
     cp /etc/ssl/certs/$cachain.chain.pem                    \
        /usr/local/share/ca-certificates/$cachain.chain.crt; \
     /usr/sbin/update-ca-certificates;                       \
     echo Added $cachain.chain.pem as trusted CA;            \
    fi

ENV REQUESTS_CA_BUNDLE /etc/ssl/certs/ca-certificates.crt

# Define default command.
CMD ["bash"]
