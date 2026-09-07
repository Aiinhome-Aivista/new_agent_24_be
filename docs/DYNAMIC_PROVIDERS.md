# Dynamic Storage & Database Providers Architecture

This document explains the architecture implemented for dynamically switching Database and Storage providers using environment variables in the TDD Agent backend.

## Overview

The application utilizes a **Strategy & Factory Pattern** to allow seamless switching between different cloud platforms (AWS, Azure) and local environments without changing the underlying business logic. 

There are two main configuration flags introduced in the `.env` file:
1. `CLOUD_PROVIDER` - Manages where files are saved (Storage).
2. `DB_PROVIDER` - Manages where the MySQL database is hosted.

---

## 1. Environment Configuration (`.env`)

To switch providers, update the following variables in your `.env` file.

### Global Flags
```env
# Storage Provider Options: DEFAULT, AWS, AZURE
CLOUD_PROVIDER=DEFAULT

# Database Provider Options: DEFAULT, AWS, AZURE
DB_PROVIDER=DEFAULT
```

### Storage Configuration Keys
Depending on the `CLOUD_PROVIDER` selected, you must provide the corresponding keys:

- **For AWS (`CLOUD_PROVIDER=AWS`)**:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_DEFAULT_REGION`
  - `AWS_S3_BUCKET_NAME`
  - `AWS_S3_BASE_FOLDER`
  - `AWS_S3_AGENT_FOLDER`

- **For Azure (`CLOUD_PROVIDER=AZURE`)**:
  - `AZURE_STORAGE_CONNECTION_STRING`
  - `AZURE_CONTAINER_NAME`

- **For Local (`CLOUD_PROVIDER=DEFAULT`)**:
  - `UPLOAD_PATH` (defaults to `data/uploads`)

### Database Configuration Keys
Depending on the `DB_PROVIDER` selected, you must provide the corresponding MySQL keys:

- **For Local (`DB_PROVIDER=DEFAULT`)**:
  - `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`

- **For AWS RDS (`DB_PROVIDER=AWS`)**:
  - `AWS_RDS_HOST`, `AWS_RDS_PORT`, `AWS_RDS_DATABASE`, `AWS_RDS_USER`, `AWS_RDS_PASSWORD`

- **For Azure Database (`DB_PROVIDER=AZURE`)**:
  - `AZURE_DB_HOST`, `AZURE_DB_PORT`, `AZURE_DB_DATABASE`, `AZURE_DB_USER`, `AZURE_DB_PASSWORD`

*(Note: All database providers currently expect a MySQL-compatible engine to ensure existing SQL queries in the repositories do not break.)*

---

## 2. Storage Architecture (`app/services/storage/`)

The storage module is responsible for persisting files (like agent responses, test cases, or context documents).

### Directory Structure
```
app/services/storage/
├── __init__.py
├── base.py           # Defines the BaseStorageProvider interface
├── factory.py        # Contains StorageFactory to route to the correct provider
├── local_storage.py  # Implements saving files to the local disk
├── aws_storage.py    # Implements saving files to AWS S3 using boto3
└── azure_storage.py  # Implements saving files to Azure Blob Storage
```

### Usage
Throughout the application, storage is accessed via `app/services/storage_service.py`, which acts as a Facade:
```python
from app.services.storage_service import save_file

# This will automatically use AWS, Azure, or Local based on the CLOUD_PROVIDER flag
file_uri = save_file(file_name, content_bytes, project_id, project_name)
```

---

## 3. Database Architecture (`app/services/db/`)

The database module isolates the connection pool initialization for different cloud database providers.

### Directory Structure
```
app/services/db/
├── __init__.py
├── base.py              # Defines the BaseDBProvider interface
├── factory.py           # Contains DBFactory to route to the correct provider
├── default_provider.py  # Initializes a MySQL connection pool for local DB
├── aws_provider.py      # Initializes a MySQL connection pool for AWS RDS
└── azure_provider.py    # Initializes a MySQL connection pool for Azure Database
```

### Usage
Database queries are executed through `app/extensions/db.py`, which securely routes requests to the active provider's pool without breaking existing application code:
```python
from app.extensions.db import query, execute, get_db_connection

# Automatically executes against Local, AWS RDS, or Azure DB based on DB_PROVIDER flag
results = query("SELECT * FROM users")
```

---

## 4. How to Add a New Provider

If you ever need to add a new provider (e.g., Google Cloud Storage or GCP Cloud SQL):

1. **Storage**:
   - Create a new file in `app/services/storage/` (e.g., `gcp_storage.py`).
   - Inherit from `BaseStorageProvider` and implement `save_file()`.
   - Update `app/services/storage/factory.py` to return your new class when `CLOUD_PROVIDER=GCP`.
   
2. **Database**:
   - Create a new file in `app/services/db/` (e.g., `gcp_provider.py`).
   - Inherit from `BaseDBProvider` and implement `init_pool()`.
   - Update `app/services/db/factory.py` to return your new class when `DB_PROVIDER=GCP`.

3. Add necessary environment variables to the `.env` file and parse them in `app/config/settings.py`.
