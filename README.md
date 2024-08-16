# LabCAS Docker Environment

This repository provides a Dockerized setup for LabCAS (Laboratory Catalog and Archive System) at JPL. It includes a `Dockerfile` and a `build_labcas.sh` script for automating the process of building and running the LabCAS environment, complete with LDAP configuration, Apache, and backend services.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Advanced Usage](#advanced-usage)
- [Contributing](#contributing)
- [License](#license)

## Overview

This project automates the deployment of the LabCAS environment using Docker. The Docker image contains all necessary dependencies, including OpenJDK, Apache, LDAP, and the LabCAS backend. The `build_labcas.sh` script simplifies the build and run process, handling LDAP initialization, Apache setup, and backend service execution.

## Prerequisites

Before you begin, ensure you have the following installed:

- [Docker](https://docs.docker.com/get-docker/)
- [Git](https://git-scm.com/)
- [Bash](https://www.gnu.org/software/bash/) (for running the provided script)
- A valid LabCAS username and password for accessing the resources

## Installation

1. **Clone the Repository**

   ```bash
   git clone https://github.com/your-username/labcas-docker.git
   cd labcas-docker

2. **Configure Credentials**

   You will need your LabCAS username and password for authentication. These can be configured directly in the `build_labcas.sh` script or passed as environment variables.

## Usage

To build and run the LabCAS Docker environment, simply execute the `build_labcas.sh` script:

```bash
./build_labcas.sh

This script will:

1. Build the Docker image from the `Dockerfile`.
2. Run the Docker container with the necessary environment variables.
3. Initialize the LDAP configuration.
4. Start the Apache server.
5. Launch the LabCAS backend services.

The script will also skip downloading any files that already exist on disk.

### Example Output

```bash
Building Docker image...
Running Docker container...
Initializing LDAP configuration...
Starting Apache service...
Starting LabCAS backend services...
LabCAS container setup completed successfully.

## Configuration

### Environment Variables

You can configure the following environment variables to customize your setup:

- `LDAP_ADMIN_USERNAME`: The LDAP admin username (default: `admin`)
- `LDAP_ADMIN_PASSWORD`: The LDAP admin password (default: `secret`)
- `LDAP_ROOT`: The LDAP root domain (default: `dc=labcas,dc=jpl,dc=nasa,dc=gov`)
- `HOST_PORT_HTTP`: The host port to map to container's port 80 (default: `80`)
- `HOST_PORT_HTTPS`: The host port to map to container's port 8444 (default: `8444`)

### Script Configuration

To modify the build and run process, you can edit the `build_labcas.sh` script. The following variables are available:

- `IMAGE_NAME`: The name of the Docker image to build (default: `labcas_debug_image`)
- `CONTAINER_NAME`: The name of the Docker container to run (default: `labcas_debug_instance`)
- `DownloadDirectory`: The directory where downloaded files are stored.

## Advanced Usage

### Dry Run

If you want to preview what will happen without actually downloading any files, you can enable the dry run mode by setting the `DryRun` variable in the `build_labcas.sh` script:

```bash
$DryRun = $true

This will output the paths of the files that would be downloaded without actually performing the downloads.

### Concurrent Jobs

You can modify the script to run multiple concurrent jobs by changing the `$Workers` variable. This allows you to download files in parallel.

```bash
$Workers = 4  # Number of parallel jobs

## Contributing

Contributions are welcome! Please fork the repository, make your changes, and submit a pull request.

## License

The project is licensed under the Apache version 2 license.
