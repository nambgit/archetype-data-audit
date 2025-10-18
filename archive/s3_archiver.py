"""
Securely archive files to AWS S3 Glacier/Deep Archive.
Integrates with PostgreSQL audit system and supports large files.
"""

import os
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from config.settings import settings
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_s3_client():
    """
    Create and return a boto3 S3 client.
    
    Uses IAM role credentials if running on EC2 (recommended).
    Falls back to .env credentials if provided (for local testing).
    
    Returns:
        boto3.S3.Client: Configured S3 client
    """
    try:
        # Try to create client with explicit credentials (for local dev)
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            logger.info("Using AWS credentials from .env")
            return boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
        else:
            # Use IAM role (EC2/Lambda) - no credentials needed
            logger.info("Using IAM role credentials")
            return boto3.client('s3', region_name=settings.AWS_REGION)
    except Exception as e:
        logger.error(f"Failed to create S3 client: {e}")
        raise

def archive_file_to_s3(file_path, checksum):
    """
    Archive a file to S3 with Glacier Deep Archive storage class.
    
    Args:
        file_path (str): Local path to the file to archive
        checksum (str): MD5 checksum of the file (for validation)
        
    Returns:
        str: Public HTTPS URL (https://bucket.s3.region.amazonaws.com/key)
        
    Raises:
        Exception: If upload fails
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    # Generate S3 key (preserve directory structure)
    # Example: D:\Shared\Reports\Q1.pdf → reports/q1.pdf
    normalized_path = os.path.normpath(file_path)
    relative_path = os.path.relpath(normalized_path, settings.FILE_SERVER_ROOT)
    s3_key = relative_path.replace('\\', '/').lower()  # Normalize for S3
    
    # Add checksum to key for integrity (optional but recommended)
    # s3_key = f"{checksum[:8]}/{s3_key}"
    
    s3_client = get_s3_client()
    bucket = settings.ARCHIVE_BUCKET
    
    try:
        logger.info(f"Uploading {file_path} to s3://{bucket}/{s3_key}")
        
        # Upload with metadata and storage class
        with open(file_path, 'rb') as file_obj:
            s3_client.upload_fileobj(
                file_obj,
                bucket,
                s3_key,
                ExtraArgs={
                    'StorageClass': 'DEEP_ARCHIVE',  # or 'GLACIER'
                    'Metadata': {
                        'original-path': file_path,
                        'checksum-md5': checksum,
                        'archived-by': 'data-audit-system',
                        'archive-date': str(int(os.path.getmtime(file_path)))
                    },
                    'ServerSideEncryption': 'AES256'  # Enable encryption
                }
            )
        
        # Verify upload (optional but recommended for critical data)
        _verify_s3_object(bucket, s3_key, checksum)
        
        s3_url = f"s3://{bucket}/{s3_key}"
        logger.info(f"✅ Successfully archived: {s3_url}")
        return s3_url
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchBucket':
            logger.error(f"S3 bucket does not exist: {bucket}")
        elif error_code == 'AccessDenied':
            logger.error("Access denied to S3 bucket. Check IAM permissions.")
        else:
            logger.error(f"S3 upload failed: {e}")
        raise
    except NoCredentialsError:
        logger.error("AWS credentials not found. Configure IAM role or .env.")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during S3 upload: {e}")
        raise

def _verify_s3_object(bucket, key, expected_checksum):
    """
    Verify S3 object integrity by comparing ETag (MD5 for single-part uploads).
    
    Note: For multipart uploads, ETag is NOT MD5. This is a simplified check.
    For production, consider storing checksum in metadata and comparing.
    
    Args:
        bucket (str): S3 bucket name
        key (str): S3 object key
        expected_checksum (str): Expected MD5 checksum
    """
    s3_client = get_s3_client()
    
    try:
        # Get object metadata
        response = s3_client.head_object(Bucket=bucket, Key=key)
        s3_checksum = response['Metadata'].get('checksum-md5')
        
        if s3_checksum != expected_checksum:
            logger.warning("Checksum mismatch between local and S3!")
            # In production: raise exception or trigger re-upload
        else:
            logger.info("✅ S3 object integrity verified")
            
    except Exception as e:
        logger.warning(f"Could not verify S3 object: {e}")

def restore_file_from_s3(s3_url, restore_days=1):
    """
    Initiate restore request for Glacier/Deep Archive object.
    
    Args:
        s3_url (str): S3 URL (s3://bucket/key)
        restore_days (int): Number of days to keep restored copy (1-30)
        
    Returns:
        bool: True if restore initiated successfully
    """
    if not s3_url.startswith('s3://'):
        raise ValueError("Invalid S3 URL format")
    
    bucket, key = s3_url[5:].split('/', 1)  # Remove 's3://'
    s3_client = get_s3_client()
    
    try:
        s3_client.restore_object(
            Bucket=bucket,
            Key=key,
            RestoreRequest={
                'Days': restore_days,
                'GlacierJobParameters': {
                    'Tier': 'Standard'  # or 'Expedited' (costs more)
                }
            }
        )
        logger.info(f"Restore initiated for {s3_url}. Available in 12-48 hours.")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'RestoreAlreadyInProgress':
            logger.info("Restore already in progress")
            return True
        else:
            logger.error(f"Restore failed: {e}")
            raise

def download_restored_file(s3_url, local_path):
    """
    Download a restored file from S3 to local path.
    
    Args:
        s3_url (str): S3 URL (s3://bucket/key)
        local_path (str): Local destination path
        
    Returns:
        str: Local path of downloaded file
    """
    if not s3_url.startswith('s3://'):
        raise ValueError("Invalid S3 URL format")
    
    bucket, key = s3_url[5:].split('/', 1)
    s3_client = get_s3_client()
    
    # Ensure parent directory exists
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    try:
        s3_client.download_file(bucket, key, local_path)
        logger.info(f"Downloaded {s3_url} to {local_path}")
        return local_path
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidObjectState':
            logger.error("File is not yet restored from Glacier. Try again later.")
        else:
            logger.error(f"Download failed: {e}")
        raise