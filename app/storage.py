"""Media storage layer.

Local development stores uploaded videos on disk. In Azure the same interface
writes to Azure Blob Storage (container "videos"), so the web tier stays
stateless and can scale horizontally.
"""
import os
import uuid


class LocalStorage:
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def save(self, file_storage, ext):
        name = f"{uuid.uuid4().hex}{ext}"
        file_storage.save(os.path.join(self.root, name))
        return name

    def url(self, name):
        return f"/media/{name}"

    def kind(self):
        return "Local disk (dev)"


class AzureBlobStorage:
    """Requires: pip install azure-storage-blob. Uses AZURE_STORAGE_CONNECTION_STRING."""

    def __init__(self, conn_str, container="videos", cdn_base=None):
        from azure.storage.blob import BlobServiceClient, ContentSettings

        self._cs = ContentSettings
        self.client = BlobServiceClient.from_connection_string(conn_str)
        self.container = self.client.get_container_client(container)
        try:
            self.container.create_container(public_access="blob")
        except Exception:
            pass  # already exists
        self.base = cdn_base or self.container.url

    def save(self, file_storage, ext):
        name = f"{uuid.uuid4().hex}{ext}"
        self.container.upload_blob(
            name,
            file_storage.stream,
            overwrite=True,
            content_settings=self._cs(content_type=file_storage.mimetype or "video/mp4"),
        )
        return name

    def url(self, name):
        return f"{self.base.rstrip('/')}/{name}"

    def kind(self):
        return "Azure Blob Storage"


def get_storage(app_root):
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if conn:
        return AzureBlobStorage(conn, cdn_base=os.environ.get("CDN_BASE_URL"))
    return LocalStorage(os.environ.get("MEDIA_DIR", os.path.join(app_root, "..", "media")))
