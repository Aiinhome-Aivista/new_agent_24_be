import boto3
from .base import BaseStorageProvider
from app.config import Config

class AwsStorageProvider(BaseStorageProvider):
    def save_file(self, file_name: str, content_bytes: bytes, project_id: int, project_name: str = "project") -> str:
        safe_project_name = "".join([c if c.isalnum() or c in (" ", "_", "-") else "_" for c in project_name]).strip().replace(" ", "_")
        folder_name = f"project_{project_id}_{safe_project_name}"
        
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
            
            # Upload to S3
            s3_client.put_object(
                Bucket=Config.AWS_S3_BUCKET_NAME,
                Key=s3_key,
                Body=content_bytes
            )
            
            s3_uri = f"s3://{Config.AWS_S3_BUCKET_NAME}/{s3_key}"
            print(f"[Storage] Saved file to AWS S3: {s3_uri}")
            return s3_uri
            
        except Exception as e:
            print(f"[Storage] Error uploading to AWS S3: {e}")
            raise e
