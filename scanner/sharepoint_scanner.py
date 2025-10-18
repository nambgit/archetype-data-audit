"""
Scan SharePoint document libraries and record file metadata into PostgreSQL.
Supports recursive folder traversal and handles large libraries via pagination.
"""

import requests
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from db.connection import get_db_connection
from auth.graph_auth import get_graph_token
from config.settings import settings

def _parse_sharepoint_datetime(datetime_str):
    """
    Parse SharePoint datetime string (ISO 8601) to timezone-aware datetime.
    
    Args:
        datetime_str (str): ISO 8601 datetime string from Graph API
        
    Returns:
        datetime: UTC timezone-aware datetime object
    """
    # Handle "Z" suffix and timezone offsets
    if datetime_str.endswith('Z'):
        dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
    else:
        dt = datetime.fromisoformat(datetime_str)
    
    # Ensure timezone-aware (Graph API always returns UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def _get_all_items_from_drive(drive_id, headers):
    """
    Recursively fetch all files from a SharePoint drive (document library).
    
    Args:
        drive_id (str): SharePoint drive ID
        headers (dict): HTTP headers with auth token
        
    Yields:
        dict: File metadata from Graph API
    """
    # Start from root
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/descendants"
    
    while url:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # Yield each file (skip folders)
        for item in data.get('value', []):
            if 'file' in item:  # Only process files, not folders
                yield item
        
        # Handle pagination (nextLink)
        url = data.get('@odata.nextLink')

def scan_sharepoint():
    """
    Scan the configured SharePoint site and sync file metadata to the audit database.
    """
    if not all([settings.SHAREPOINT_SITE_ID, settings.GRAPH_CLIENT_ID, 
                settings.GRAPH_TENANT_ID, settings.GRAPH_CLIENT_SECRET]):
        print("[WARN] SharePoint credentials missing in .env. Skipping scan.")
        return

    try:
        # Get access token
        token = get_graph_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        # Extract site ID components (format: hostname,site-id,web-id)
        site_parts = settings.SHAREPOINT_SITE_ID.split(',')
        if len(site_parts) != 3:
            raise ValueError("SHAREPOINT_SITE_ID must be in format: hostname,site-id,web-id")
        
        hostname, site_id, web_id = site_parts
        
        # Get site drive (document library)
        site_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{site_id}"
        site_response = requests.get(site_url, headers=headers)
        site_response.raise_for_status()
        site_data = site_response.json()
        
        drive_id = site_data['drive']['id']
        print(f"[INFO] Scanning SharePoint drive: {drive_id}")
        
        # Process all files
        file_count = 0
        for item in _get_all_items_from_drive(drive_id, headers):
            try:
                # Extract metadata
                file_path = item['webUrl']
                last_modified = _parse_sharepoint_datetime(item['lastModifiedDateTime'])
                created_time = _parse_sharepoint_datetime(item['createdDateTime'])
                owner = item.get('createdBy', {}).get('user', {}).get('displayName', 'Unknown')
                
                # Generate checksum (simulate - in real app, download file content)
                # Note: For large files, consider using file size + modified time as proxy
                checksum_input = f"{file_path}{last_modified.isoformat()}".encode()
                checksum = hashlib.md5(checksum_input).hexdigest()
                
                # Save to database
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO file_audit 
                            (source, file_path, last_modified, last_accessed, owner, checksum)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (file_path) DO UPDATE SET
                                last_modified = EXCLUDED.last_modified,
                                last_accessed = EXCLUDED.last_accessed,
                                checksum = EXCLUDED.checksum,
                                status = 'Active',
                                updated_at = CURRENT_TIMESTAMP
                        """, (
                            "sharepoint",
                            file_path,
                            last_modified,
                            last_modified,  # SharePoint doesn't provide last_accessed
                            owner,
                            checksum
                        ))
                    conn.commit()
                
                file_count += 1
                if file_count % 50 == 0:
                    print(f"[INFO] Processed {file_count} SharePoint files...")
                    
            except Exception as e:
                print(f"[ERROR] Failed to process SharePoint file {item.get('name', 'unknown')}: {e}")
        
        print(f"✅ SharePoint scan completed. Processed {file_count} files.")
        
    except Exception as e:
        print(f"[ERROR] SharePoint scan failed: {e}")
        raise