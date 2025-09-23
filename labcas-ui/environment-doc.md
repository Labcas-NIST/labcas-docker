# LabCAS Environment Configuration Reference

This document explains each key found in `assets/conf/environment.cfg` and how it influences LabCAS UI behavior.


The environment configuration sets up base URLs, feature toggles, default headers and filter lists used across the LabCAS interface. The keys are loaded into browser `localStorage` at login.

## Basic environment

- **environment_name** – identifier for the running site (e.g. `edrn`). Drives template paths such as sidebars.
- **environment** – base URL for API requests. Used by utility functions to build service calls.
- **environment_url** – external homepage for the consortium. Linked from headers and footers.
- **leadpi_url**, **institution_url**, **organ_url**, **protocol_url** – base links to lead investigator, institution, organ and protocol information pages. 
- **allow_redirect** – when `true`, unauthenticated users are redirected to the login page.

## SSO
- **sso_login_url** – sso url endpoint to retrieve SSO login.
- **sso_redirect_url** –  url for sso to redirect back.
- **sso_enabled** – toggle for SSO or basic auth.

## User access messaging

- **error_msg** – HTML shown when login fails.
- **accept_msg** – Data use agreement displayed before login when enabled.
- **login_msg** – Instructions presented on the login page.

## Machine-learning Widget

- **ml_wizard_html** – HTML template loaded into the ML wizard modal.
- **ml_wizard_options** – comma-separated list of pipeline option keys and labels. Used to populate the ML pipeline selector. 
- **ml_wizard_nuclei_options** – additional HTML fragment for the nuclei detection pipeline.

## Download helpers

- **download_script_win** / **download_script** – example scripts for Windows (PowerShell) and Linux downloads. Values contain placeholders replaced by the client.

## Dataset display settings

- **dataset_header_order** – CSV list of dataset metadata fields to show, in order.
- **dataset_header_hide** – fields hidden from the details table.
- **dataset_id_append** – dataset fields whose IDs are appended in parentheses after their value.

## Collection display settings

- **collection_header_order** – fields shown on the collection details page.
- **collection_header_hide** – fields hidden on the collection page. 
- **collection_header_extend_* and dataset_header_extend_* ** – collection-specific additional headers displayed for listed collections.
- **collapsible_headers** – collection fields that are initially collapsed.
- **collection_id_append** – collection fields for which IDs are appended.

## Search configuration

- **escape_characters** – characters escaped in search queries.
- **filters** – high level filter groups (Core, Pathology, Aperio).
- **Core_filters_id**, **Core_filters_display**, **Core_filters_div** – IDs, display labels and `<div>` targets for Core filters.
- **Pathology_filters_id**, **Pathology_filters_display**, **Pathology_filters_div** – definitions for Pathology filters.
- **Aperio_filters_id**, **Aperio_filters_display**, **Aperio_filters_div** – definitions for Aperio image filters.

## External service APIs

- **ksdb_institution_site_api**, **ksdb_person_api** – APIs for institution and person data.
- **ksdb_labcas_search_name_api**, **ksdb_labcas_search_protocol_api**, **ksdb_labcas_search_profile_api** – endpoints used by advanced search features.
- **ksdb_labcas_search_profile_save**, **ksdb_labcas_search_profile_delete** – endpoints for saving and deleting saved searches.
- **ksdb_labcas_acceptance_check**, **ksdb_labcas_acceptance_save** – APIs used to store user acceptance of terms.
- **ksdb_labcas_dicom_state_name_api** – used to retrieve DICOM state names.

## Image services

- **dsa_api** – base URL of the Girder/DSA API for image retrieval.
- **dsa_image_viewer** – histomics image viewer prefix.

## Support information

- **support_contact** – email displayed when automated operations fail.
- **ksdb_split_key** – delimiter for KSDB API parameters.

## Data paths and image display

- **labcas_data.collection_path_maps** – maps collection IDs to subdirectories used by the viewer.
- **dataset_image_hide** – datasets whose images are suppressed in viewers.
- **edrn_protocol_prefix** – prefix URL used when rendering protocol links.
- **ml_enabled_collections** – collections that enable the machine learning widget.
- **image_viewer_enabled_collections** – collections allowed in the image viewer.

## Download thresholds

- **file_size_threshold_for_download_alert_trigger** and **file_count_threshold_for_download_alert_trigger** – if exceeded, users receive a warning before downloading.
- **DOWNLOAD_THRESHOLD** – minimum total file size at which a dataset download prompts the user to use the script-based method.
- **file_size_upper_limit** – maximum file size allowed for a single request.

## Metadata table mapping

- **metadata_table_collection_mapping** – mapping from collection IDs to tab names used by the metadata table view.

