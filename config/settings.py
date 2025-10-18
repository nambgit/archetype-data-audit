import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

class PostgresSettings:
    # PostgreSQL Database
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    DB_NAME = os.getenv("DB_NAME", "audit_db")
    DB_USER = os.getenv("DB_USER", "audit_user")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    
    # File Server Root Path
    FILE_SERVER_ROOT = os.getenv("FILE_SERVER_ROOT", "D:\\Shared")
    SHAREPOINT_SITE_ID = os.getenv("SHAREPOINT_SITE_ID")
    GRAPH_CLIENT_ID = os.getenv("GRAPH_CLIENT_ID")
    GRAPH_TENANT_ID = os.getenv("GRAPH_TENANT_ID")
    GRAPH_CLIENT_SECRET = os.getenv("GRAPH_CLIENT_SECRET")
    
    # S3 Storage
    ARCHIVE_BUCKET = os.getenv("ARCHIVE_BUCKET", "data-audit-archive-2025")
    AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-1")
    
    # Web UI Configuration
    WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT = int(os.getenv("WEB_PORT", "5000"))
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin123!")

settings = PostgresSettings()