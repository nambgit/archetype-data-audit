"""
Scan SharePoint document libraries and record file metadata into PostgreSQL.
Supports recursive folder traversal and handles large libraries via pagination.
"""

import requests
import hashlib
import logging
from datetime import datetime, timezone
from db.connection import get_db_connection
from auth.graph_auth import get_graph_token
from config.settings import settings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _parse_sharepoint_datetime(datetime_str):
    """Parse SharePoint datetime string (ISO 8601) to timezone-aware datetime."""
    if not datetime_str:
        return None
    
    try:
        if datetime_str.endswith('Z'):
            dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(datetime_str)
        
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as e:
        logger.error(f"Failed to parse datetime '{datetime_str}': {e}")
        return None


def _get_all_items_from_drive(drive_id, headers):
    """
    Recursively fetch all files from a SharePoint drive using delta query.
    Delta query is the recommended approach for scanning entire drives.
    """
    # Use delta query to get all items efficiently
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/delta"
    
    page_count = 0
    while url:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            page_count += 1
            items = data.get('value', [])
            logger.debug(f"Page {page_count}: {len(items)} items")
            
            for item in items:
                # Only yield files (not folders) and not deleted items
                if 'file' in item and not item.get('deleted'):
                    yield item
            
            # Check for next page
            url = data.get('@odata.nextLink')
            
            # If no nextLink, check for deltaLink (end of sync)
            if not url and '@odata.deltaLink' in data:
                logger.debug("Reached end of delta sync")
                break
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching items: {e}")
            break


def _get_all_items_recursive(drive_id, headers, folder_id='root'):
    """
    Alternative method: Recursively fetch all files using /children endpoint.
    This is a fallback if delta query doesn't work.
    """
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{folder_id}/children"
    
    while url:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            for item in data.get('value', []):
                if 'file' in item:
                    # It's a file, yield it
                    yield item
                elif 'folder' in item:
                    # It's a folder, recurse into it
                    logger.debug(f"Scanning folder: {item.get('name')}")
                    yield from _get_all_items_recursive(drive_id, headers, item['id'])
            
            # Handle pagination
            url = data.get('@odata.nextLink')
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching items from folder {folder_id}: {e}")
            break


def scan_sharepoint():
    """Scan the configured SharePoint site and sync file metadata to the audit database."""
    
    # Validate credentials
    if not all([settings.SHAREPOINT_SITE_ID, settings.GRAPH_CLIENT_ID, 
                settings.GRAPH_TENANT_ID, settings.GRAPH_CLIENT_SECRET]):
        logger.warning("SharePoint credentials missing in .env. Skipping scan.")
        return

    try:
        logger.info("=" * 60)
        logger.info("Starting SharePoint scan...")
        logger.info("=" * 60)
        
        # Step 1: Get access token
        logger.info("\n[Step 1/4] Getting access token...")
        token = get_graph_token()
        if not token:
            raise ValueError("Failed to get access token")
        
        logger.info(f"✓ Token obtained (length: {len(token)})")
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        # Step 2: Validate Site ID format
        logger.info("\n[Step 2/4] Validating site ID...")
        site_id = settings.SHAREPOINT_SITE_ID.strip()
        site_parts = site_id.split(',')
        
        if len(site_parts) != 3:
            raise ValueError(
                f"SHAREPOINT_SITE_ID must be in format: hostname,site-id,web-id\n"
                f"Got: {site_id}\n"
                f"Example: techtus087.sharepoint.com,819683ff-604e-4f01-ae5d-ca364732aafc,e6d41e53-780b-4564-b44a-dd1f1c91d8da"
            )
        
        logger.info(f"✓ Site ID format valid: {site_id}")
        
        # Step 3: Access site and get drive
        logger.info("\n[Step 3/4] Accessing SharePoint site...")
        
        # First, verify site exists
        site_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}"
        logger.info(f"Testing site access: {site_url}")
        
        try:
            site_response = requests.get(site_url, headers=headers, timeout=30)
            site_response.raise_for_status()
            site_data = site_response.json()
            
            site_name = site_data.get('displayName', 'Unknown')
            site_weburl = site_data.get('webUrl', 'N/A')
            logger.info(f"✓ Site found: {site_name}")
            logger.info(f"  URL: {site_weburl}")
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                logger.error(
                    "\n❌ 401 UNAUTHORIZED - Token does not have permission!\n\n"
                    "FIX THIS IN AZURE PORTAL:\n"
                    "1. Go to: Azure AD → App Registrations → [Your App]\n"
                    "2. Click 'API permissions'\n"
                    "3. Click 'Add a permission' → Microsoft Graph → Application permissions\n"
                    "4. Add these permissions:\n"
                    "   ☐ Sites.Read.All (or Sites.ReadWrite.All)\n"
                    "   ☐ Files.Read.All (or Files.ReadWrite.All)\n"
                    "5. Click 'Grant admin consent for [Organization]' ⚠️ CRITICAL!\n"
                    "6. Wait 5-10 minutes, then try again\n\n"
                    f"Error details: {e}"
                )
            elif e.response.status_code == 403:
                logger.error(f"\n❌ 403 FORBIDDEN - App lacks permissions: {e}")
            elif e.response.status_code == 404:
                logger.error(
                    f"\n❌ 404 NOT FOUND - Site ID is incorrect!\n"
                    f"Site ID: {site_id}\n"
                    f"Check that this is the correct composite ID format."
                )
            else:
                logger.error(f"\n❌ HTTP {e.response.status_code}: {e}")
            raise
        
        # Now get the drive (document library)
        drive_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive"
        logger.info(f"Getting default drive...")
        
        try:
            drive_response = requests.get(drive_url, headers=headers, timeout=30)
            drive_response.raise_for_status()
            drive_data = drive_response.json()
            
            drive_id = drive_data['id']
            drive_name = drive_data.get('name', 'Documents')
            drive_weburl = drive_data.get('webUrl', 'N/A')
            
            logger.info(f"✓ Drive found: {drive_name}")
            logger.info(f"  Drive ID: {drive_id}")
            logger.info(f"  Drive URL: {drive_weburl}")
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.error(
                    "\n❌ 404 NOT FOUND - Site has no default document library!\n"
                    "This site might not have a 'Documents' library."
                )
            raise
        
        # Step 4: Scan files
        logger.info("\n[Step 4/4] Scanning files...")
        logger.info("-" * 60)
        
        file_count = 0
        error_count = 0
        
        # Try delta query first (recommended method)
        logger.info("Using delta query to fetch all files...")
        
        try:
            for item in _get_all_items_from_drive(drive_id, headers):
                try:
                    file_path = item.get('webUrl')
                    if not file_path:
                        error_count += 1
                        continue
                    
                    last_modified = _parse_sharepoint_datetime(item.get('lastModifiedDateTime'))
                    if not last_modified:
                        error_count += 1
                        continue
                    
                    owner = item.get('createdBy', {}).get('user', {}).get('displayName', 'Unknown')
                    
                    # Generate checksum (metadata-based since we're not downloading files)
                    checksum_input = f"{file_path}{last_modified.isoformat()}".encode()
                    checksum = hashlib.md5(checksum_input).hexdigest()
                    
                    # Insert to database
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
                                    owner = EXCLUDED.owner,
                                    status = 'Active',
                                    updated_at = CURRENT_TIMESTAMP
                            """, (
                                "sharepoint",
                                file_path,
                                last_modified,
                                last_modified,
                                owner,
                                checksum
                            ))
                        conn.commit()
                    
                    file_count += 1
                    if file_count % 50 == 0:
                        logger.info(f"Processed {file_count} files...")
                        
                except Exception as e:
                    error_count += 1
                    file_name = item.get('name', 'unknown')
                    logger.error(f"Failed to process file '{file_name}': {e}")
                    
        except Exception as e:
            logger.error(f"Delta query failed: {e}")
            logger.info("Falling back to recursive /children method...")
            
            # Fallback: use recursive children method
            file_count = 0
            error_count = 0
            
            for item in _get_all_items_recursive(drive_id, headers):
                try:
                    file_path = item.get('webUrl')
                    if not file_path:
                        error_count += 1
                        continue
                    
                    last_modified = _parse_sharepoint_datetime(item.get('lastModifiedDateTime'))
                    if not last_modified:
                        error_count += 1
                        continue
                    
                    owner = item.get('createdBy', {}).get('user', {}).get('displayName', 'Unknown')
                    
                    checksum_input = f"{file_path}{last_modified.isoformat()}".encode()
                    checksum = hashlib.md5(checksum_input).hexdigest()
                    
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
                                    owner = EXCLUDED.owner,
                                    status = 'Active',
                                    updated_at = CURRENT_TIMESTAMP
                            """, (
                                "sharepoint",
                                file_path,
                                last_modified,
                                last_modified,
                                owner,
                                checksum
                            ))
                        conn.commit()
                    
                    file_count += 1
                    if file_count % 50 == 0:
                        logger.info(f"Processed {file_count} files...")
                        
                except Exception as e:
                    error_count += 1
                    file_name = item.get('name', 'unknown')
                    logger.error(f"Failed to process file '{file_name}': {e}")
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("✅ SharePoint scan completed!")
        logger.info(f"Files processed: {file_count}")
        logger.info(f"Errors: {error_count}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"\n❌ SharePoint scan failed: {e}")
        raise


if __name__ == "__main__":
    scan_sharepoint()