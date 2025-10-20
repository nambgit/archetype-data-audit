"""
Scan local file server, SharePoint and record file metadata into PostgreSQL.
Automatically archive files not accessed in >180 days.
"""

import os
import hashlib
from datetime import datetime, timezone, timedelta
from db.connection import get_db_connection
from config.settings import settings

def _compute_file_checksum(file_path, chunk_size=8192):
    """
    Compute MD5 checksum of a file in chunks to handle large files efficiently.
    
    Args:
        file_path (str): Path to the file
        chunk_size (int): Size of chunks to read (default: 8KB)
        
    Returns:
        str: Hexadecimal MD5 checksum
        
    Raises:
        IOError: If file cannot be read
    """
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def scan_file_server():
    """
    Recursively scan the configured file server root directory.
    For each file:
      - Compute MD5 checksum
      - Record metadata in PostgreSQL database
      - Archive to S3 if last accessed > 180 days ago
      - Update database status accordingly
    """
    root = settings.FILE_SERVER_ROOT
    if not os.path.exists(root):
        print(f"[WARN] File server path not found: {root}")
        return

    # Define archive threshold (180 days ago in UTC)
    now_utc = datetime.now(timezone.utc)
    archive_threshold = now_utc - timedelta(days=180)

    print(f"[INFO] Starting file server scan at: {root}")
    print(f"[INFO] Archive threshold: {archive_threshold.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    processed_count = 0
    archived_count = 0

    # Walk through all directories and files
    for dirpath, dirnames, filenames in os.walk(root):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)

            try:
                # Skip if file is currently locked/used by another process
                if not os.access(filepath, os.R_OK):
                    print(f"[SKIP] File not readable (locked?): {filepath}")
                    continue

                # Get file stats
                stat = os.stat(filepath)

                # Convert Unix timestamps to timezone-aware datetime (UTC)
                last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                last_accessed = datetime.fromtimestamp(stat.st_atime, tz=timezone.utc)

                # Compute MD5 checksum
                checksum = _compute_file_checksum(filepath)

                # Save metadata to database
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
                        """, ("fileserver", filepath, last_modified, last_accessed, "system", checksum))
                    conn.commit()
                
                processed_count += 1

                # Get current time in UTC (timezone-aware)
                now_utc = datetime.now(timezone.utc)

                # Check if file should be archived
                if last_accessed < archive_threshold:
                    print(f"[ARCHIVE] File eligible for archiving: {filepath}")

                    try:
                        # Attempt to archive to S3
                        from archive.s3_archiver import archive_file_to_s3
                        s3_url = archive_file_to_s3(filepath)

                        # Remove original file after successful upload
                        os.remove(filepath)
                    
                        # Update database status
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("""
                                    UPDATE file_audit 
                                    SET status = 'Archived', archive_url = %s 
                                    WHERE file_path = %s
                                """, (s3_url, filepath))
                            conn.commit()
                        archived_count += 1
                        print(f"[SUCCESS] Archived and removed: {filepath}")

                    except Exception as archive_error:
                        print(f"[ERROR] Failed to archive {filepath}: {archive_error}")
                        # Optional: Mark as 'ArchiveFailed' in DB
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("""
                                    UPDATE file_audit 
                                    SET status = 'ArchiveFailed' 
                                    WHERE file_path = %s
                                """, (filepath,))
                            conn.commit()

                # Progress indicator (every 100 files)
                if processed_count % 100 == 0:
                    print(f"[PROGRESS] Processed {processed_count} files...")

            except PermissionError:
                print(f"[PERMISSION] Access denied: {filepath}")
            except FileNotFoundError:
                # File was deleted during scan
                print(f"[MISSING] File deleted during scan: {filepath}")
            except Exception as e:
                print(f"[ERROR] Unexpected error processing {filepath}: {e}")
                
    print(f"✅ File server scan completed.")
    print(f"   Total files processed: {processed_count}")
    print(f"   Files archived: {archived_count}")