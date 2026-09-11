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
ARG LABCAS_UI_REPO=github.com:yuliujpl/labcas-nist-private.git
ARG LABCAS_UI_BRANCH=microbial_strain
ARG GITHUB_TOKEN
RUN set -eu; \
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

file_index = root / "f/index.html"
if file_index.exists():
    text = file_index.read_text(encoding="utf-8")
    old = '''      var get_var = get_url_vars();
      let file_id = localStorage.getItem("file_id");'''
    new = '''      var get_var = get_url_vars();
      let file_id = get_var["file_id"] || localStorage.getItem("file_id");
      if (file_id) {
        file_id = decodeURIComponent(file_id);
        localStorage.setItem("file_id", file_id);
      }'''
    if old in text:
        file_index.write_text(text.replace(old, new, 1), encoding="utf-8")

authentication_js = root / "assets/js/labcas/authentication.js"
if authentication_js.exists():
    text = authentication_js.read_text(encoding="utf-8")
    text = text.replace(
        '''$("#download_icon").attr("onclick","download_file('"+html_safe_id+"','single');");''',
        '''$("#download_icon").off("click").on("click", function() { download_file(html_safe_id, "single"); });'''
    )
    text = text.replace(
        '''$("#download_metadata_icon").attr("onclick","download_metadata_file('"+html_safe_id+"','single');");''',
        '''$("#download_metadata_icon").off("click").on("click", function() { download_metadata_file(html_safe_id, "single"); });'''
    )
    authentication_js.write_text(text, encoding="utf-8")
PY

# Add local NIST customizations that are not in the upstream UI branch.
COPY overlays/ /tmp/labcas-ui-overlays/
RUN cp -R /tmp/labcas-ui-overlays/. /var/www/html/labcas-ui/

# Wire the cell expansion Gantt overlay into collection and dataset pages.
RUN python3 - <<'PY'
from pathlib import Path

root = Path("/var/www/html/labcas-ui")

def replace_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected snippet not found in {path}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

c_index = root / "c" / "index.html"
replace_once(
    c_index,
    '<h4 class="card-title">Cell Line Gantt</h4>',
    '<h4 class="card-title" id="collection_level_gantt_title">Cell Line Gantt</h4>',
)
replace_once(
    c_index,
    '<iframe id="collection_level_gantt_frame" style="border: none; box-shadow: -2px 2px 2px 2px rgba(0,0,0,0.75); transform: translate(-2px, 2px);" height="350px" width="100%"></iframe>',
    '<iframe id="collection_level_gantt_frame" style="border: none; box-shadow: -2px 2px 2px 2px rgba(0,0,0,0.75); transform: translate(-2px, 2px);" height="430px" width="100%"></iframe>',
)
replace_once(
    c_index,
    '''      if (get_var["collection_id"] != "Cell_Line_Provenance") {
        $("#collection_level_gantt").hide();
      }else{
        $('#collection_level_gantt_frame').attr('src', '/labcas-ui/a/gantt2.html');
      }''',
    '''      var collection_id = get_var["collection_id"];
      if (collection_id == "cell_expansion_collection" || collection_id == "Cell_Expansion_Collection" || collection_id == "Cell_Line_Provenance_John") {
        $("#collection_level_gantt_title").text("Cell Expansion Gantt");
        $('#collection_level_gantt_frame').attr('src', '/labcas-ui/a/cell-expansion-gantt.html?collection_id=' + encodeURIComponent(collection_id));
      } else if (collection_id != "Cell_Line_Provenance") {
        $("#collection_level_gantt").hide();
      } else {
        $("#collection_level_gantt_title").text("Cell Line Gantt");
        $('#collection_level_gantt_frame').attr('src', '/labcas-ui/a/gantt2.html');
      }''',
)

d_index = root / "d" / "index.html"
replace_once(
    d_index,
    '<iframe frameBorder="0" height="285px" width="100%" src="/labcas-ui/a/gantt.html"></iframe>',
    '<iframe id="dataset_level_gantt_frame" frameBorder="0" height="430px" width="100%" src="/labcas-ui/a/gantt.html"></iframe>',
)

datasets_js = root / "assets" / "js" / "labcas" / "datasets.js"
replace_once(
    datasets_js,
    '''        if ( collectionid != "cell_line_provenance"){
            $("#collection_level_gantt").hide();
        }else{
            $("#collection_level_gantt").show();
        }''',
    '''        if (collectionid == "cell_expansion_collection") {
            $("#collection_level_gantt").css("visibility", "visible").show();
            $("#dataset_level_gantt_frame, #metadata_div iframe").attr("src", "/labcas-ui/a/cell-expansion-gantt.html?dataset_id=" + encodeURIComponent(get_var["dataset_id"] || ""));
        } else if (collectionid == "cell_line_provenance") {
            $("#collection_level_gantt").css("visibility", "visible").show();
            $("#dataset_level_gantt_frame, #metadata_div iframe").attr("src", "/labcas-ui/a/gantt.html");
        } else {
            $("#collection_level_gantt").hide();
        }''',
)
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
