# web/app.py
"""
Flask web interface for IT Admins to view and manage archived files.
Authenticates against Active Directory (LDAP) and supports restore/download.
"""

from flask import (
    Flask, render_template, request, Response, send_file, stream_with_context,
    redirect, url_for, session, flash
)
from functools import wraps
from db.connection import get_db_connection
from config.settings import settings
from archive.s3_archiver import download_restored_file, restore_file_from_s3
from auth.ldap_auth import authenticate_user
import os
import logging
import requests
import base64

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "")  # Required for sessions

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

#def check_auth(username, password):
#    """Validate admin credentials."""
#    return username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD

#def authenticate():
#    """Send 401 response for unauthorized access."""
#    return Response(
#        'IT Admin Login Required', 401,
#        {'WWW-Authenticate': 'Basic realm="Audit System"'}
#    )


# === Authentication Decorator ===
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# === Routes Login ===
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if authenticate_user(username, password):
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    return render_template('login.html')

# === Routes Logout ===
@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def dashboard():
    #auth = request.authorization

    #if not auth or not check_auth(auth.username, auth.password):
    #    return authenticate()

    # Fetch latest 10 records from database """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM file_audit ORDER BY created_at DESC LIMIT 20")
            files = cur.fetchall()

            # Fetch total counts by status (for stats cards)
            cur.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE status = 'Archived') AS archived_count,
                    COUNT(*) FILTER (WHERE status = 'Restoring') AS restoring_count
                FROM file_audit
            """)
            counts = cur.fetchone()
            total_archived = counts['archived_count'] or 0
            total_restoring = counts['restoring_count'] or 0
    return render_template(
        'index.html',
        files=files,
        total_archived=total_archived,
        total_restoring=total_restoring
    )

def download_from_sharepoint(file_url, filename):
    """
    Stream download a file from SharePoint using Graph API.
    
    Args:
        file_url: SharePoint file webUrl
        filename: Filename for download
        
    Returns:
        Flask Response with file stream
    """
    try:
        from auth.graph_auth import get_graph_token
        
        logger.info(f"[SharePoint] Downloading: {filename}")
        logger.info(f"[SharePoint] URL: {file_url}")
        
        # Get access token
        token = get_graph_token()
        if not token:
            logger.error("[SharePoint] Failed to get Graph API token")
            return "SharePoint authentication failed. Check Graph API credentials.", 500
        
        headers = {
            'Authorization': f'Bearer {token}'
        }
        
        # Create sharing token from URL for Graph API
        # SharePoint Graph API uses shares endpoint with encoded URL
        encoded_url = base64.b64encode(file_url.encode()).decode()
        # Make URL-safe base64 (Graph API requirement)
        sharing_token = encoded_url.replace('=', '').replace('/', '_').replace('+', '-')
        sharing_token = f"u!{sharing_token}"
        
        download_api_url = f"https://graph.microsoft.com/v1.0/shares/{sharing_token}/driveItem/content"
        
        logger.info(f"[SharePoint] Requesting from: {download_api_url}")
        
        # Stream the file from SharePoint
        def generate():
            try:
                with requests.get(download_api_url, headers=headers, stream=True, timeout=120) as r:
                    # Handle common errors
                    if r.status_code == 404:
                        logger.error(f"[SharePoint] File not found: {file_url}")
                        yield b"ERROR: File not found in SharePoint. The file may have been moved or deleted."
                        return
                    
                    if r.status_code == 401:
                        logger.error("[SharePoint] Access denied - token invalid or expired")
                        yield b"ERROR: SharePoint access denied. Please check API permissions."
                        return
                    
                    if r.status_code == 403:
                        logger.error("[SharePoint] Forbidden - insufficient permissions")
                        yield b"ERROR: Insufficient permissions to access this file."
                        return
                    
                    # Raise for other HTTP errors
                    r.raise_for_status()
                    
                    # Stream file in chunks
                    bytes_downloaded = 0
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            yield chunk
                            bytes_downloaded += len(chunk)
                    
                    logger.info(f"[SharePoint] Successfully downloaded {bytes_downloaded} bytes: {filename}")
                
            except requests.exceptions.Timeout:
                logger.error(f"[SharePoint] Timeout downloading: {filename}")
                yield b"ERROR: Download timeout. The file may be too large or network is slow."
            
            except requests.exceptions.RequestException as e:
                logger.error(f"[SharePoint] Request error: {e}")
                yield f"ERROR: Failed to download file - {str(e)}".encode()
            
            except Exception as e:
                logger.error(f"[SharePoint] Unexpected error: {e}", exc_info=True)
                yield f"ERROR: Unexpected error - {str(e)}".encode()
        
        return Response(
            stream_with_context(generate()),
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': 'application/octet-stream'
            }
        )
        
    except Exception as e:
        logger.error(f"[SharePoint] Download setup failed: {e}", exc_info=True)
        return f"SharePoint download failed: {str(e)}", 500

def download_from_fileserver(file_path, filename):
    """
    Download a file from file server (local filesystem or mounted network share).
    
    Args:
        file_path: Full path to file on file server
        filename: Filename for download
        
    Returns:
        Flask Response with file
    """
    try:
        logger.info(f"[FileServer] Downloading: {filename}")
        logger.info(f"[FileServer] Path: {file_path}")
        
        # Check if file exists
        if not os.path.exists(file_path):
            logger.error(f"[FileServer] File not found: {file_path}")
            return (
                "File not found on file server. Possible reasons:\n"
                "- File was moved or deleted\n"
                "- Network share is not mounted\n"
                "- Path is incorrect\n"
                f"Path: {file_path}"
            ), 404
        
        # Check if path is a file (not directory)
        if not os.path.isfile(file_path):
            logger.error(f"[FileServer] Path is not a file: {file_path}")
            return f"Path exists but is not a file: {file_path}", 400
        
        # Check read permissions
        if not os.access(file_path, os.R_OK):
            logger.error(f"[FileServer] No read permission: {file_path}")
            return f"Permission denied. Flask app cannot read this file: {file_path}", 403
        
        # Get file size for logging
        file_size = os.path.getsize(file_path)
        logger.info(f"[FileServer] File size: {file_size} bytes")
        
        # Send file
        logger.info(f"[FileServer] Sending file: {filename}")
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"[FileServer] Download failed: {e}", exc_info=True)
        return f"File server download failed: {str(e)}", 500

@app.route('/download/<int:file_id>')
@login_required
def download_file(file_id):
    """
    Download a file by its ID.
    Supports SharePoint and File Server sources only.
    """
    """ auth = request.authorization
    #if not auth or not check_auth(auth.username, auth.password):
    #    return authenticate()"""

    try:
        # Get file info from database
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT source, file_path, status
                    FROM file_audit 
                    WHERE id = %s
                """, (file_id,))
                
                row = cur.fetchone()
                
                if not row:
                    logger.error(f"File ID {file_id} not found in database")
                    return "File not found in database", 404
                
                source = row['source']
                file_path = row['file_path']
                status = row['status']
        
        # Extract filename from path/URL
        filename = os.path.basename(file_path)
        
        logger.info(f"Download request - ID: {file_id}, Source: {source}, Status: {status}, File: {filename}")
        
        # Check status
        if status != 'Active':
            logger.warning(f"File status is not Active: {status}")
            return f"File is not available for download. Current status: {status}", 400
        
        # Route to appropriate download handler based on source
        if source == 'sharepoint':
            return download_from_sharepoint(file_path, filename)
        
        elif source == 'fileserver':
            return download_from_fileserver(file_path, filename)
        
        else:
            logger.error(f"Unsupported source type: {source}")
            return (
                f"Unsupported file source: {source}\n\n"
                "This system only supports:\n"
                "- sharepoint: Files stored in SharePoint Online\n"
                "- fileserver: Files stored on file server or network shares"
            ), 400
    
    except Exception as e:
        logger.error(f"Download error for file_id {file_id}: {e}", exc_info=True)
        return f"Download failed: {str(e)}", 500

@app.route('/restore/<int:file_id>')
@login_required
def restore_file(file_id):
    """Initiate restore from S3 Glacier and update DB status."""
    """auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return authenticate()"""
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Get archive URL
            cur.execute("SELECT archive_url, file_path FROM file_audit WHERE id = %s", (file_id,))
            row = cur.fetchone()
            
            if not row or not row['archive_url']:
                return "File not archived", 400
            
            s3_url = row['archive_url']
            original_path = row['file_path']
            
            try:
                # Initiate S3 restore
                restore_file_from_s3(s3_url, restore_days=5)
                
                # Update status to 'Restoring'
                cur.execute("""
                    UPDATE file_audit 
                    SET status = 'Restoring' 
                    WHERE id = %s
                """, (file_id,))
                conn.commit()
                
                return "Restore initiated. File will be available in 12-48 hours.", 202
            except Exception as e:
                print(f"[ERROR] Restore failed: {e}")
                return "Restore failed", 500

# === Run app ===
if __name__ == "__main__":
    from config.settings import settings
    app.run(
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        debug=False
    )