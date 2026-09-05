import os
try:
    import boto3
except ImportError:
    boto3 = None
from app.config.settings import Config

def save_file(file_name: str, content_bytes: bytes, project_id: int, project_name: str = "project") -> str:
    """
    Saves file either to local storage or AWS S3 based on Config.DEPLOY.
    Returns the storage URI or path.
    """
    # Clean up project_name to be file-system friendly
    safe_project_name = "".join([c if c.isalnum() or c in (" ", "_", "-") else "_" for c in project_name]).strip().replace(" ", "_")
    folder_name = f"project_{project_id}_{safe_project_name}"
    
    if Config.DEPLOY and Config.AWS_S3_BUCKET_NAME:
        try:
            s3_client = boto3.client(
                's3',
                aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
                region_name=Config.AWS_DEFAULT_REGION
            )
            
            # Construct S3 Object Key: <base>/<agent>/<project_id_name>/<file_name>
            key_parts = []
            if Config.AWS_S3_BASE_FOLDER:
                key_parts.append(Config.AWS_S3_BASE_FOLDER)
            if Config.AWS_S3_AGENT_FOLDER:
                key_parts.append(Config.AWS_S3_AGENT_FOLDER)
            
            key_parts.append(folder_name)
            key_parts.append(file_name)
            
            s3_key = "/".join(key_parts)
            
            s3_client.put_object(
                Bucket=Config.AWS_S3_BUCKET_NAME,
                Key=s3_key,
                Body=content_bytes
            )
            
            return f"s3://{Config.AWS_S3_BUCKET_NAME}/{s3_key}"
        except Exception as e:
            print(f"[Storage] Failed to upload to S3: {e}")
            raise e
    else:
        # Save locally
        local_dir = os.path.join(Config.UPLOAD_PATH, folder_name)
        os.makedirs(local_dir, exist_ok=True)
        
        file_path = os.path.join(local_dir, file_name)
        with open(file_path, "wb") as f:
            f.write(content_bytes)
            
        return file_path
