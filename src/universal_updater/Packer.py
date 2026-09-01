import zipfile
import rarfile
import py7zr
import pathlib
import os
import shutil
import tempfile
import colorama
import logging

from universal_updater.Helpers import Helpers


class Packer:
    """Handles unpacking and repacking of compressed files."""

    def __init__(self, update_folder_path, save_format_type, disable_clean):
        """
        Initialize the Packer with configurations.

        :param update_folder_path: Path to the update folder
        :param save_format_type: Format type for saving compressed files
        :param disable_clean: Flag to disable cleaning
        """
        self.update_folder_path = update_folder_path
        self.save_format_type = save_format_type
        self.disable_clean = disable_clean
        self.tool_name = ""
        self.tool_config = {}
        self.valid_extensions = ['.zip', '.rar', '.7z']

    def tool_setup(self, tool_name, tool_config):
        """
        Initialize tool-specific settings.

        :param tool_name: Name of the tool
        :param tool_config: Configuration object for the specific tool
        """
        self.tool_name = tool_name
        self.tool_config = tool_config

    def unpack_zip(self, file_path, unpack_path, file_pass=None):
        """
        Unpack a ZIP file.

        :param file_path: Path to the ZIP file
        :param unpack_path: Destination path to unpack
        :param file_pass: Password for the ZIP file, default is None
        """
        if file_pass:
            file_pass = bytes(file_pass, 'utf-8')
        
        with zipfile.ZipFile(file_path, 'r') as compressed:
            compressed.extractall(unpack_path, pwd=file_pass)

    def unpack_rar(self, file_path, unpack_path, file_pass=None):
        """
        Unpack a RAR file.

        :param file_path: Path to the RAR file
        :param unpack_path: Destination path to unpack
        :param file_pass: Password for the RAR file, default is None
        """
        # download first "UnRAR for Windows" from https://www.rarlab.com/rar_add.htm
        # direct link: https://www.rarlab.com/rar/unrarw32.exe
        # new link: https://www.win-rar.com/predownload.html?&Version=32bit&L=0.
        with rarfile.RarFile(file_path, 'r') as compressed:
            compressed.extractall(unpack_path, pwd=file_pass)

    def unpack_7z(self, file_path, unpack_path, file_pass=None):
        """
        Unpack a 7z file.

        :param file_path: Path to the 7z file
        :param unpack_path: Destination path to unpack
        :param file_pass: Password for the 7z file, default is None
        """
        with py7zr.SevenZipFile(file_path, 'r', password=file_pass) as compressed:
            compressed.extractall(unpack_path)

    def unpack(self, file_path, unpack_path, file_pass=None):
        """
        Unpack a compressed file based on its extension.

        :param file_path: Path to the compressed file
        :param unpack_path: Destination path to unpack
        :param file_pass: Password for the compressed file, default is None
        :return: True if unpacked, False if extension not supported
        :raises Exception: If an error occurs during unpacking
        """
        file_ext = pathlib.Path(file_path).suffix.lower()
        if file_ext not in self.valid_extensions:
            return False

        try:
            if file_ext == '.zip':
                self.unpack_zip(file_path, unpack_path, file_pass)
            elif file_ext == '.rar':
                self.unpack_rar(file_path, unpack_path, file_pass)
            elif file_ext == '.7z':
                self.unpack_7z(file_path, unpack_path, file_pass)
        except Exception as error:
            raise Exception(colorama.Fore.RED + f'An error occurred during unpacking: {error}')

        return True

    def unpack_nested(self, unpack_path):
        """
        Check for and unpack nested compressed files (zip inside a zip).

        :param unpack_path: Path to the unpacked folder
        """
        folder_list = os.listdir(unpack_path)
        if len(folder_list) == 1:
            nested_file = pathlib.Path(unpack_path).joinpath(folder_list[0])
            if self.unpack(nested_file, unpack_path):
                os.remove(nested_file)

    def unpack_step(self, file_path):
        """
        Perform the unpack step for a specific tool.

        :param file_path: Path to the compressed file
        :return: Path to the unpacked folder
        """
        unpack_path = pathlib.Path(file_path).parent
        update_file_pass = self.tool_config.get('update_file_pass', None)

        if self.unpack(file_path, unpack_path, update_file_pass):
            os.remove(file_path)

            # dirty hack for correct zip inside a zip...
            self.unpack_nested(unpack_path)

        return unpack_path

    def repack_save_compress_name(self, name, version):
        """
        Generate the compressed file name based on the save format type.

        :param name: Name of the tool
        :param version: Version of the tool
        :return: Compressed file name
        """
        pack_name = f'{name} - {version}.7z'
        if self.save_format_type == 'version':
            pack_name = f'{version}.7z'
        elif self.save_format_type == 'name':
            pack_name = f'{name}.7z'

        return pack_name

    def repack_merge(self, tool_folder_path, tool_unpack_path):
        """
        Merge the new unpacked version with the old one.

        :param tool_folder_path: Path to the tool folder
        :param tool_unpack_path: Path to the unpacked folder
        :return: None
        """
        # checks and preparation
        old_version = self.tool_config.get('local_version', '0')
        old_compress_name = self.repack_save_compress_name(self.tool_name, old_version)
        old_tool_compress_path = tool_folder_path.joinpath(old_compress_name)
        if not old_tool_compress_path.exists():
            return False

        logging.info(f'{self.tool_name}: merging with "{old_compress_name}"')

        # unpack old version into an isolated temp folder outside update_folder_path.
        # tool_unpack_path can equal update_folder_path (when the archive has no single
        # wrapping folder, see FileManager.processing_tool_path), so a path built under
        # update_folder_path would end up nested inside tool_unpack_path and get wiped
        # by the rmtree below before the final move.
        old_tool_unpack_path = pathlib.Path(tempfile.mkdtemp(
            prefix=f'{self.tool_name}_merge_',
            dir=pathlib.Path(self.update_folder_path).parent,
        ))
        try:
            self.unpack(old_tool_compress_path, old_tool_unpack_path)

            # merge
            shutil.copytree(tool_unpack_path, old_tool_unpack_path, copy_function=shutil.copy, dirs_exist_ok=True)
            shutil.rmtree(tool_unpack_path)
            shutil.move(old_tool_unpack_path, tool_unpack_path, copy_function=shutil.copy)
        finally:
            if old_tool_unpack_path.exists():
                Helpers.delete_folder(old_tool_unpack_path, ignore_errors=True)

    def repack_step(self, tool_folder_path, tool_unpack_path, version):
        """
        Perform the repack step for a specific tool.

        :param tool_folder_path: Path to the tool folder
        :param tool_unpack_path: Path to the unpacked folder
        :param version: Version of the tool
        :return: Dictionary containing tool name, tool folder, and compressed file name
        """
        use_merge = Helpers.config_flag(self.tool_config, 'merge')
        if use_merge:
            self.repack_merge(tool_folder_path, tool_unpack_path)

        logging.info(f'{self.tool_name}: saving to folder {tool_folder_path}')

        save_compress_name = self.repack_save_compress_name(self.tool_name, version)

        # Build the archive in an isolated temp folder unique to this run, rather than
        # a path shared across tools (previously update_folder_path.parent, the common
        # "updates" root): with save_format_type "version", two tools resolving to the
        # same version string could race on an identical filename there. A folder under
        # update_folder_path itself isn't safe either: tool_unpack_path can equal
        # update_folder_path (no single wrapping folder, see
        # FileManager.processing_tool_path), which would put the archive being written
        # inside the very directory it's reading from.
        repack_temp_path = pathlib.Path(tempfile.mkdtemp(
            prefix=f'{self.tool_name}_repack_',
            dir=pathlib.Path(self.update_folder_path).parent,
        ))
        try:
            tool_repack_path = repack_temp_path.joinpath(save_compress_name)

            with py7zr.SevenZipFile(tool_repack_path, 'w') as archive:
                for item in sorted(pathlib.Path(tool_unpack_path).iterdir()):
                    archive.writeall(item, item.name)

            if not self.disable_clean:
                Helpers.cleanup_folder(tool_folder_path)

            shutil.copy(tool_repack_path, tool_folder_path)
        finally:
            Helpers.delete_folder(repack_temp_path, ignore_errors=True)

        return {
            'tool_name': self.tool_name,
            'tool_folder': str(tool_folder_path),
            'save_compress_name': save_compress_name,
        }
