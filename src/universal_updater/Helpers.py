import pathlib
import shutil
from urllib.parse import urlparse


class Helpers:

    @staticmethod
    def cleanup_folder(path):
        """
        Clean up a folder by deleting all its contents.
        """
        for file in pathlib.Path(path).iterdir():
            if file.is_dir():
                shutil.rmtree(file)
            else:
                file.unlink()

    @staticmethod
    def is_valid_url(url: str) -> bool:
        """
        Return True if URL has a valid HTTP/S scheme and network location.
        """
        parts = urlparse(url)
        return parts.scheme in ("http", "https") and bool(parts.netloc)
