FROM python:3.10-slim

ARG PIP_EXTRA_INDEX_URL=https://pypi.org/simple
ENV PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}

# Build publish from the local checkout inside the Airflow image.
RUN apt-get update && apt-get install -y \
    git gcc libglib2.0-dev libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev \
    libopenjp2-7-dev libtiff-dev ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/publish
COPY . /opt/publish

# install Publish and its deps
RUN python -m pip install --upgrade pip setuptools wheel
RUN if [ -f setup.py ]; then pip install . ; \
    elif [ -f requirements.txt ]; then pip install --extra-index-url "$PIP_EXTRA_INDEX_URL" -r requirements.txt ; fi

# Optional patch scripts provided by labcas-docker repo
RUN if [ -f /opt/publish/patch_publishing_pipeline.py ]; then python3 /opt/publish/patch_publishing_pipeline.py; fi

# Override runtime configs to use /data/archive and /mnt/metadata
RUN if [ -f /opt/publish/basic.py.patched ]; then cp /opt/publish/basic.py.patched /opt/publish/src/configs/basic.py; fi
RUN if [ -f /opt/publish/solr.py.patched ]; then cp /opt/publish/solr.py.patched /opt/publish/src/plugins/publish_db_ops/solr.py; fi

# Trust LabCAS backend cert if provided
RUN if [ -f /opt/publish/labcas-ssl-cert.pem ]; then \
      cp /opt/publish/labcas-ssl-cert.pem /usr/local/share/ca-certificates/labcas-ssl-cert.crt && \
      update-ca-certificates; \
    fi

ENV PYTHONPATH=/opt/publish/src

# keep container alive for docker exec workflows
ENTRYPOINT ["tail", "-f", "/dev/null"]
