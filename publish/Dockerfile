# Build the publish tool locally instead of pulling the upstream image.
# This Dockerfile should be updated with the actual build steps for the publish tool.

FROM python:3.10-slim

ARG GITHUB_TOKEN
RUN apt-get update && apt-get install -y git gcc libglib2.0-dev libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev libopenjp2-7-dev libtiff-dev && rm -rf /var/lib/apt/lists/*

# clone the Publish repo (token optional for private repos)
RUN git clone https://$GITHUB_TOKEN@github.com/jpl-labcas/publish.git /opt/publish
WORKDIR /opt/publish

# install Publish and its deps
RUN if [ -f setup.py ]; then pip install . ; \
    elif [ -f requirements.txt ]; then pip install -r requirements.txt ; fi
# ------------------------------------------------------------------
# Patch configs/basic.py so Publish uses env vars and /data/archive
# ------------------------------------------------------------------
RUN python - <<'PY'
import pathlib, textwrap, sys, os

root = pathlib.Path(".")
matches = list(root.rglob("configs/basic.py"))
if not matches:
    sys.stderr.write("ERROR: configs/basic.py not found in publish repo\n")
    sys.exit(1)

patch = textwrap.dedent("""
# -------- patched by labcas-docker build --------
import os
import pathlib
import sys

consortium        = os.getenv('PUBLISH_CONSORTIUM', 'EDRN')
# Prefer lowercase legacy env if provided, else fall back to PUBLISH_COLLECTION
collection        = os.getenv('collection', os.getenv('PUBLISH_COLLECTION', 'Basophile'))
print('DEBUG ENV collection=', os.getenv('collection'))
print('DEBUG ENV PUBLISH_COLLECTION=', os.getenv('PUBLISH_COLLECTION'))
collection_subset = os.getenv('PUBLISH_COLLECTION_SUBSET', '')
archive_dir       = '/data/archive'
publish_id        = os.getenv('PUBLISH_ID', '')
steps             = os.getenv('PUBLISH_STEPS', 'publish')

print(f"DEBUG: Using archive_dir: {archive_dir}")
if not pathlib.Path(archive_dir).exists():
    print(f"DEBUG: archive_dir does NOT exist: {archive_dir}")
    sys.stderr.write("ERROR: archive_dir does NOT exist: {}\\n".format(archive_dir))
else:
    print(f"DEBUG: archive_dir exists: {archive_dir}")

# ------------------------------------------------
""").lstrip()

for cfg in matches:
    original = cfg.read_text()
    cfg.write_text(patch + "\n\n# ---- original below ----\n" + original)
    print(f"Patched {cfg}")
PY
COPY patch_publishing_pipeline.py /opt/publish/patch_publishing_pipeline.py

# Patch publishing_pipeline.py to add debug prints
RUN python3 /opt/publish/patch_publishing_pipeline.py

# Override Solr push plugin with guarded required-field fills for LabCAS cores
COPY solr.py.patched /opt/publish/src/plugins/publish_db_ops/solr.py

# ensure src-layout package is on PYTHONPATH
ENV PYTHONPATH=/opt/publish/src

# Add self-signed LabCAS backend certificate to trusted CA certificates
COPY labcas-ssl-cert.pem /usr/local/share/ca-certificates/labcas-ssl-cert.crt
RUN apt-get update && apt-get install -y ca-certificates && update-ca-certificates

# keep container alive by tailing /dev/null
ENTRYPOINT ["tail", "-f", "/dev/null"]
