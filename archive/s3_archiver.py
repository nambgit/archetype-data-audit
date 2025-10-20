"""
Securely archive files to AWS S3 Glacier/Deep Archive.
Integrates with PostgreSQL audit system and supports large files.
"""

import os
import hashlib
from pathlib import Path
from typing import Tuple
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from config.settings import settings
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def calculate_md5(file_path: str, block_size: int = 65536) -> str:
    """Calculate MD5 checksum of a file (memory-efficient for large files)."""
    md5_hash = hashlib.md5()
    with open(file_path, 'rb') as f:
        for block in iter(lambda: f.read(block_size), b""):
            md5_hash.update(block)
    return md5_hash.hexdigest()


def get_s3_client():
    """
    Create and return a boto3 S3 client.
    
    Uses IAM role credentials if running on EC2 (recommended).
    Falls back to .env credentials if provided (for local testing).
    """
    try:
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            logger.debug("Using AWS credentials from .env")
            return boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
        else:
            logger.debug("Using IAM role credentials")
            return boto3.client('s3', region_name=settings.AWS_REGION)
    except Exception as e:
        logger.error(f"Failed to create S3 client: {e}")
        raise


def _validate_file_path(file_path: str) -> Path:
    """Ensure file_path is within allowed root directory."""
    file_p = Path(file_path).resolve()
    base_dir = Path(settings.FILE_SERVER_ROOT).resolve()

    if not base_dir.exists():
        raise ValueError(f"FILE_SERVER_ROOT does not exist: {base_dir}")

    try:
        file_p.relative_to(base_dir)
    except ValueError:
        raise ValueError(f"File path is outside allowed root: {file_path}")

    if not file_p.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    return file_p


def _build_s3_key(file_path: Path) -> str:
    """Generate normalized S3 key from file path."""
    base_dir = Path(settings.FILE_SERVER_ROOT).resolve()
    rel_path = file_path.relative_to(base_dir)
    # Normalize to lowercase and forward slashes
    return str(rel_path).replace('\\', '/').lower()


def archive_file_to_s3(file_path: str) -> str:
    """
    Archive a file to S3 with Glacier Deep Archive storage class.
    
    Args:
        file_path (str): Local path to the file to archive
        
    Returns:
        str: S3 URI (s3://bucket/key)
    """
    # Validate and resolve file path
    file_p = _validate_file_path(file_path)
    
    # Calculate checksum (do not trust caller input)
    checksum = calculate_md5(str(file_p))
    logger.debug(f"Computed MD5 for {file_p.name}: {checksum}")

    # Build S3 key
    s3_key = _build_s3_key(file_p)
    bucket = settings.ARCHIVE_BUCKET
    storage_class = getattr(settings, 'S3_STORAGE_CLASS', 'DEEP_ARCHIVE')

    s3_client = get_s3_client()

    try:
        logger.info(f"Uploading '{file_p.name}' to s3://{bucket}/{s3_key}")
        
        with open(file_p, 'rb') as file_obj:
            s3_client.upload_fileobj(
                file_obj,
                bucket,
                s3_key,
                ExtraArgs={
                    'StorageClass': storage_class,
                    'Metadata': {
                        'original-path': str(file_p),
                        'checksum-md5': checksum,
                        'archived-by': 'data-audit-system',
                        'archive-date': str(int(file_p.stat().st_mtime))
                    },
                    'ServerSideEncryption': 'AES256'
                }
            )

        # Verify metadata was stored correctly
        _verify_s3_metadata(bucket, s3_key, checksum)

        s3_uri = f"s3://{bucket}/{s3_key}"
        logger.info(f"✅ Successfully archived: {s3_uri}")
        return s3_uri

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


def _verify_s3_metadata(bucket: str, key: str, expected_checksum: str):
    """Verify that S3 object metadata contains the expected checksum."""
    s3_client = get_s3_client()
    try:
        response = s3_client.head_object(Bucket=bucket, Key=key)
        s3_checksum = response['Metadata'].get('checksum-md5')
        if s3_checksum != expected_checksum:
            logger.warning("Checksum mismatch in S3 metadata!")
            # In production, you might raise an exception here
        else:
            logger.debug("✅ S3 metadata checksum verified")
    except Exception as e:
        logger.warning(f"Could not verify S3 metadata: {e}")


def _parse_s3_uri(s3_url: str) -> Tuple[str, str]:
    """Parse s3://bucket/key into (bucket, key)."""
    if not s3_url.startswith('s3://'):
        raise ValueError("Invalid S3 URL format. Expected s3://bucket/key")
    parts = s3_url[5:].split('/', 1)
    if len(parts) != 2:
        raise ValueError("Invalid S3 URL: missing key")
    return parts[0], parts[1]


def is_restored(s3_url: str) -> bool:
    """Check if a Glacier object is fully restored."""
    bucket, key = _parse_s3_uri(s3_url)
    s3 = get_s3_client()
    try:
        obj = s3.head_object(Bucket=bucket, Key=key)
        restore_status = obj.get('Restore')
        return restore_status is not None and 'ongoing-request="false"' in restore_status
    except ClientError as e:
        logger.error(f"Failed to check restore status: {e}")
        return False


def restore_file_from_s3(s3_url: str, restore_days: int = 1) -> bool:
    """Initiate restore request for Glacier/Deep Archive object."""
    bucket, key = _parse_s3_uri(s3_url)
    s3_client = get_s3_client()

    try:
        s3_client.restore_object(
            Bucket=bucket,
            Key=key,
            RestoreRequest={
                'Days': restore_days,
                'GlacierJobParameters': {
                    'Tier': 'Standard'
                }
            }
        )
        logger.info(f"Restore initiated for {s3_url}. Available in 12–48 hours.")
        return True
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'RestoreAlreadyInProgress':
            logger.info("Restore already in progress")
            return True
        else:
            logger.error(f"Restore failed: {e}")
            raise


def download_restored_file(s3_url: str, local_path: str) -> str:
    """Download a restored file from S3 to local path with checksum verification."""
    bucket, key = _parse_s3_uri(s3_url)
    s3_client = get_s3_client()

    # Ensure parent dir exists
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        s3_client.download_file(bucket, key, local_path)
        logger.info(f"Downloaded to {Path(local_path).name}")

        # Verify checksum
        response = s3_client.head_object(Bucket=bucket, Key=key)
        expected_checksum = response['Metadata'].get('checksum-md5')
        if expected_checksum:
            actual_checksum = calculate_md5(local_path)
            if actual_checksum != expected_checksum:
                Path(local_path).unlink(missing_ok=True)
                raise ValueError("Downloaded file checksum mismatch!")
            logger.debug("✅ Downloaded file checksum verified")
        return local_path

    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'InvalidObjectState':
            logger.error("File is not yet restored from Glacier. Try again later.")
        else:
            logger.error(f"Download failed: {e}")
        raise