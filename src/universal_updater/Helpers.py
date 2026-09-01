import os
import stat
import pathlib
import shutil
from urllib.parse import urlparse


class Helpers:

    @staticmethod
    def _clear_readonly(func, path, exc_info):
        """
        Error handler for shutil.rmtree: clears the read-only attribute and retries.
        """
        os.chmod(path, stat.S_IWRITE)
        func(path)

    @staticmethod
    def cleanup_folder(path):
        """
        Clean up a folder by deleting all its contents.
        """
        for file in pathlib.Path(path).iterdir():
            if file.is_dir():
                shutil.rmtree(file, onerror=Helpers._clear_readonly)
            else:
                try:
                    file.unlink()
                except PermissionError:
                    os.chmod(file, stat.S_IWRITE)
                    file.unlink()

    @staticmethod
    def delete_folder(path, ignore_errors=True):
        """
        Delete a folder and all its contents. When ignore_errors is False,
        clears the read-only attribute and retries instead of raising
        (files extracted from some archives come out read-only on Windows).
        """
        shutil.rmtree(path, ignore_errors=ignore_errors, onerror=None if ignore_errors else Helpers._clear_readonly)

    _TRUE_VALUES = {'true', '1', 'yes', 'on'}

    @staticmethod
    def config_flag(config, key, default=False):
        """
        Read a boolean flag from a tool_config dict. configparser values are
        always strings, so a plain `.get(key, False)` truthy-check is wrong:
        e.g. "disable_repack = false" in tools.ini would evaluate as True.
        """
        value = config.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in Helpers._TRUE_VALUES

    @staticmethod
    def build_result(tool_name, tool_folder_path, save_compress_name=''):
        """
        Build the standard processing-step result dict consumed by
        Updater.post_update's hook calls.

        :param tool_name: Name of the tool
        :param tool_folder_path: Path to the tool's install folder
        :param save_compress_name: Name of the repacked archive, if any
        :return: Dictionary with 'tool_name', 'tool_folder' and 'save_compress_name'
        """
        return {
            'tool_name': tool_name,
            'tool_folder': str(tool_folder_path),
            'save_compress_name': save_compress_name,
        }

    @staticmethod
    def is_valid_url(url: str) -> bool:
        """
        Return True if URL has a valid HTTP/S scheme and network location.
        """
        parts = urlparse(url)
        return parts.scheme in ("http", "https") and bool(parts.netloc)

    @staticmethod
    def get_filename_from_url(url: str) -> str:
        """
        Extract the filename from a URL, stripping fragments and queries.
        """
        fragment_removed = url.split('#')[0]  # keep to left of first "#"
        query_string_removed = fragment_removed.split('?')[0]
        scheme_removed = query_string_removed.split('://')[-1].split(':')[-1]

        if scheme_removed.find('/') == -1:
            return ''

        return pathlib.Path(scheme_removed).name
