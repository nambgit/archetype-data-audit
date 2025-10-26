import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

class PostgresSettings:
    # PostgreSQL Database
    DB_HOST = os.getenv("DB_HOST", "")
    DB_PORT = int(os.getenv("DB_PORT", ""))
    DB_NAME = os.getenv("DB_NAME", "")
    DB_USER = os.getenv("DB_USER", "")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    
    # File Server Root Path
    FILE_SERVER_ROOT = os.getenv("FILE_SERVER_ROOT", "")
    SHAREPOINT_SITE_ID = os.getenv("SHAREPOINT_SITE_ID", "")
    GRAPH_CLIENT_ID = os.getenv("GRAPH_CLIENT_ID", "")
    GRAPH_TENANT_ID = os.getenv("GRAPH_TENANT_ID", "")
    GRAPH_CLIENT_SECRET = os.getenv("GRAPH_CLIENT_SECRET", "")
    
    # --- Active Directory / LDAP ---
    AD_SERVER: str = os.getenv("AD_SERVER", "")
    AD_PORT: int = int(os.getenv("AD_PORT", ""))    
    AD_USE_SSL: bool = os.getenv("AD_USE_SSL", "true").lower() == "true"
    AD_BASE_DN: str = os.getenv("AD_BASE_DN", "dc=archetype,dc=local")
    LDAP_SKIP_CERT_VERIFY: bool = os.getenv("LDAP_SKIP_CERT_VERIFY", "false").lower() == "true"
    #AD_BIND_USER: str = os.getenv("AD_BIND_USER", "") 
    #AD_BIND_PASSWORD: str = os.getenv("AD_BIND_PASSWORD", "")

    # AWS
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    ARCHIVE_BUCKET = os.getenv("ARCHIVE_BUCKET", "")
    AWS_REGION = os.getenv("AWS_REGION", "")
    S3_STORAGE_CLASS = "DEEP_ARCHIVE"  # or "GLACIER"

    # Web UI Configuration
    WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT = int(os.getenv("WEB_PORT", "5000"))
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

settings = PostgresSettings()