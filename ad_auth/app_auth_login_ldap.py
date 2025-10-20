# web/app.py
"""
Flask web interface for IT Admins to view and manage archived files.
Authenticates against Active Directory (LDAP) and supports restore/download.
"""

from flask import (
    Flask, render_template, request, Response, send_file,
    redirect, url_for, session, flash
)
from functools import wraps
from db.connection import get_db_connection
from config.settings import settings
from archive.s3_archiver import download_restored_file, restore_file_from_s3
from auth.ldap_auth import authenticate_user
import os

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "")  # Required for sessions


# === Authentication Decorator ===
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# === Routes ===
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


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def dashboard():
    """Render the main dashboard with latest file audit records."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM file_audit ORDER BY created_at DESC LIMIT 10")
            files = cur.fetchall()
    return render_template('index.html', files=files)


@app.route('/download/<int:file_id>')
@login_required
def download_file(file_id):
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

            if status == 'Archived':
                return "File is in Glacier storage. Click 'Restore' first.", 400
                
            if status == 'Restoring':
                return "File is being restored from Glacier. Try again in 12-48 hours.", 400

            if status == 'Active':
                if os.path.exists(original_path):
                    return send_file(original_path, as_attachment=True)
                else:
                    return "Local file missing", 404

            # Archived + Restored → download from S3
            try:
                filename = os.path.basename(original_path)
                temp_path = f"/tmp/restored_{filename}"
                download_restored_file(s3_url, temp_path)
                response = send_file(temp_path, as_attachment=True, download_name=filename)
                # Optional: schedule cleanup or use after_request hook
                return response
            except Exception as e:
                return f"Download failed: {str(e)}", 500


@app.route('/restore/<int:file_id>')
@login_required
def restore_file(file_id):
    """Initiate restore from S3 Glacier and update DB status."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT archive_url FROM file_audit WHERE id = %s", (file_id,))
            row = cur.fetchone()
            
            if not row or not row['archive_url']:
                return "File not archived", 400
            
            s3_url = row['archive_url']
            
            try:
                restore_file_from_s3(s3_url, restore_days=5)
                cur.execute("UPDATE file_audit SET status = 'Restoring' WHERE id = %s", (file_id,))
                conn.commit()
                return "Restore initiated. File will be available in 12-48 hours.", 202
            except Exception as e:
                print(f"[ERROR] Restore failed: {e}")
                return "Restore failed", 500


# === Run app ===
if __name__ == "__main__":
    app.run(
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        debug=False
    )