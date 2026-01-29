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


FROM edrndocker/labcas-ubuntubase
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

# Clone LabCAS UI repository from configurable repo (default private), use configured branch
ARG LABCAS_UI_REPO=github.com:Labcas-NIST/Labcas-ui.git
ARG LABCAS_UI_BRANCH=microbial_strain
ARG GITHUB_TOKEN
RUN set -eux; \
    repo_url="${LABCAS_UI_REPO}"; \
    if [ -n "${GITHUB_TOKEN:-}" ]; then \
      # Inject token into HTTPS URL for private repo access (not needed for public repo)
      proto=$(echo "$repo_url" | sed -E 's|^(https?)://.*|\1|'); \
      host_path=$(echo "$repo_url" | sed -E 's|^https?://||'); \
      if [ "$proto" = "http" ] || [ "$proto" = "https" ]; then \
        repo_url="${proto}://${GITHUB_TOKEN}@${host_path}"; \
      fi; \
    fi; \
    git clone --single-branch --branch "$LABCAS_UI_BRANCH" "$repo_url" /var/www/html/labcas-ui

# Patch UI base-path handling to avoid null ui_base_path after login
RUN python3 - <<'PY'
from pathlib import Path
import re

root = Path("/var/www/html/labcas-ui")

for html in root.rglob("*.html"):
    try:
        text = html.read_text(encoding="utf-8")
    except Exception:
        continue
    if "pathname.startswith" in text:
        text = text.replace("pathname.startswith", "pathname.startsWith")
        html.write_text(text, encoding="utf-8")

login_js = root / "assets/js/labcas/login.js"
if login_js.exists():
    text = login_js.read_text(encoding="utf-8")
    if 'localStorage.setItem("ui_base_path"' not in text:
        pattern = re.compile(
            r"(\\n\\s*if \\(base\\) \\{[\\s\\S]*?\\n\\s*\\}\\n)"
            r"(\\s*if \\(path && path\\[0\\] !== \"/\"\\) \\{)",
            re.MULTILINE,
        )
        insert = (
            "\\n    if (base && localStorage && !localStorage.getItem(\"ui_base_path\")) {"
            "\\n        localStorage.setItem(\"ui_base_path\", base);"
            "\\n    }\\n"
        )
        new_text, count = pattern.subn(r"\\1" + insert + r"\\2", text, count=1)
        if count:
            login_js.write_text(new_text, encoding="utf-8")
PY

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
