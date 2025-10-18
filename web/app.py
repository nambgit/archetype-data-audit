"""
Flask web interface for IT Admins to view and manage archived files.
Includes basic authentication and file restore/download actions.
"""

from flask import Flask, render_template, request, Response
from db.connection import get_db_connection
from config.settings import settings

# Initialize Flask app
app = Flask(__name__)

def check_auth(username, password):
    """Validate admin credentials."""
    return username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD

def authenticate():
    """Send 401 response for unauthorized access."""
    return Response(
        'IT Admin Login Required', 401,
        {'WWW-Authenticate': 'Basic realm="Audit System"'}
    )

@app.route('/')
def dashboard():
    """Render the main dashboard with latest file audit records."""
    auth = request.authorization
    #if not auth or auth.username != settings.ADMIN_USERNAME or auth.password != settings.ADMIN_PASSWORD:
    if not auth or not check_auth(auth.username, auth.password):
        return authenticate()

    # Fetch latest 10 records from database
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM file_audit ORDER BY created_at DESC LIMIT 10")
            files = cur.fetchall()

    return render_template('index.html', files=files)

@app.route('/download/<int:file_id>')
def download_file(file_id):
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return authenticate()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT archive_url, status, file_path 
                FROM file_audit 
                WHERE id = %s
            """, (file_id,))
            row = cur.fetchone()
            
            if not row:
                return "File not found", 404
                
            s3_url = row['archive_url']
            status = row['status']
            original_path = row['file_path']

            # If archived but not restored → block download
            if status == 'Archived':
                return "File is in Glacier storage. Click 'Restore' first.", 400
                
            # If restoring → inform user
            if status == 'Restoring':
                return "File is being restored from Glacier. Try again in 12-48 hours.", 400

            # If Active → file is local (not archived)
            if status == 'Active':
                if os.path.exists(original_path):
                    return send_file(original_path, as_attachment=True)
                else:
                    return "Local file missing", 404

            # If Archived + Restored → download from S3
            try:
                from archive.s3_archiver import download_restored_file
                temp_path = f"/tmp/restored_{os.path.basename(original_path)}"
                download_restored_file(s3_url, temp_path)
                return send_file(temp_path, as_attachment=True)
            except Exception as e:
                return f"Download failed: {str(e)}", 500

@app.route('/restore/<int:file_id>')
def restore_file(file_id):
    """Initiate restore from S3 Glacier and update DB status."""
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return authenticate()
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Get archive URL
            cur.execute("SELECT archive_url FROM file_audit WHERE id = %s", (file_id,))
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

if __name__ == "__main__":
    from config.settings import settings
    app.run(
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        debug=False
    )