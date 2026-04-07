import os
import pathlib
import shutil
import colorama
import logging

from universal_updater.Helpers import Helpers


class FileManager:
    """Handles file and folder operations like cleanup and copy."""

    def __init__(self, script_path, disable_clean):
        """
        Initialize FileManager with script path and clean option.

        :param script_path: Path to the script
        :param disable_clean: Flag to disable folder cleanup
        """
        self.script_path = script_path
        self.disable_clean = disable_clean
        self.tool_name = ""
        self.tool_config = {}

    def tool_setup(self, tool_name, tool_config):
        """
        Initialize tool-specific settings.

        :param tool_name: Name of the tool
        :param tool_config: Configuration object for the specific tool
        """
        self.tool_name = tool_name
        self.tool_config = tool_config

    def get_tool_install_path(self):
        """
        Retrieve the installation path for the tool.

        :return: Absolute path object for the tool's installation folder
        """
        folder = self.tool_config.get('folder')
        if not folder:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: "folder" key is required in config')

        tool_folder_path = pathlib.Path(folder)
        if not tool_folder_path.is_absolute():
            tool_folder_path = pathlib.Path(self.script_path).joinpath(tool_folder_path)

        return tool_folder_path.resolve(strict=False)

    def processing_tool_path(self, tool_unpack_path):
        """
        Process and return the tool's folder and unpack paths.

        :param tool_unpack_path: Path-like where the tool is unpacked
        :return: Dict with 'folder_path' and 'unpack_path' as pathlib.Path objects
        """
        # If the archive contains a single non-empty root directory, descend into it.
        # This handles the common case where a zip/7z wraps everything inside one folder.
        # A single file (not a directory) is left as-is to avoid incorrectly flattening
        # archives that legitimately contain only one file at the root.
        folder_list = os.listdir(tool_unpack_path)
        if len(folder_list) == 1:
            folder_sample = pathlib.Path(tool_unpack_path).joinpath(folder_list[0])
            if folder_sample.is_dir() and any(folder_sample.iterdir()):
                tool_unpack_path = folder_sample

        # tool folder
        tool_folder_path = self.get_tool_install_path()
        tool_folder_path.mkdir(parents=True, exist_ok=True)

        return {
            'folder_path': tool_folder_path,
            'unpack_path': tool_unpack_path,
        }

    def save(self, tool_folder_path, tool_unpack_path):
        """
        Save the tool to the specified folder path.

        :param tool_folder_path: Path to the folder where the tool will be saved
        :param tool_unpack_path: Path where the tool is unpacked
        :return: Dictionary containing 'tool_name', 'tool_folder', and 'save_compress_name'
        """
        logging.info(f'{self.tool_name}: saving to folder {tool_folder_path}')

        use_merge = self.tool_config.get('merge', None)
        if not self.disable_clean and not use_merge:
            Helpers.cleanup_folder(tool_folder_path)

        shutil.copytree(tool_unpack_path, tool_folder_path, copy_function=shutil.copy, dirs_exist_ok=True)

        return {
            'tool_name': self.tool_name,
            'tool_folder': str(tool_folder_path),
            'save_compress_name': '',
        }
