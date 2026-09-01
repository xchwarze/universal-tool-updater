import os
import pathlib
import colorama
import logging

from universal_updater.HttpClient import HttpClient
from universal_updater.Scraper import Scraper
from universal_updater.Downloader import Downloader
from universal_updater.Packer import Packer
from universal_updater.FileManager import FileManager
from universal_updater.ScriptExecutor import ScriptExecutor
from universal_updater.Helpers import Helpers


class Updater:
    """
    Manages the update process for a tool. The class is responsible for
    scraping the latest version, downloading updates, unpacking, and saving or
    repacking the tool. It also handles pre-update and post-update scripts.
    """

    def __init__(self, config_manager, tool_name, updater_setup=None, shutdown_event=None):
        """
        Initialize the Updater and all its collaborators for this tool.

        :param config_manager: Configuration manager instance
        :param tool_name: Name of the tool this Updater instance will process
        :param updater_setup: Dictionary containing various flags and settings for the updater.
            Possible keys are:
            - force_download: Flag to force download
            - disable_repack: Flag to disable repacking
            - disable_clean: Flag to disable cleaning
            - disable_install_check: Flag to disable installation check
            - disable_progress: Flag to disable progress bar
            - save_format_type: Format type for saving (default "full")
            - use_github_api: Flag to use GitHub API. The value is the token to use the api.
        :param shutdown_event: threading.Event signaling a graceful-shutdown request, or None
        :raises Exception: If tool_name has no matching section in tools.ini
        """
        updater_setup = updater_setup or {}
        self.shutdown_event = shutdown_event
        self.tool_name = tool_name
        self.config_manager = config_manager
        self.tool_config = config_manager.get_tool_config(tool_name)
        self.script_path = os.getcwd()
        self.update_folder_path = pathlib.Path(self.script_path) / 'updates' / tool_name
        self.disable_install_check = updater_setup.get('disable_install_check', False)
        self.disable_repack = updater_setup.get('disable_repack', True)
        self.dry_run = updater_setup.get('dry_run', False)

        http_client = HttpClient(
            tool_name=tool_name,
            user_agent='curl/7.84.0',
            request_timeout=updater_setup.get('request_timeout', 30),
            request_retries=updater_setup.get('download_retries', 3),
        )
        self.scraper = Scraper(
            tool_name, self.tool_config, http_client,
            force_download=updater_setup.get('force_download', False),
            use_github_api=updater_setup.get('use_github_api', ''),
        )
        self.downloader = Downloader(
            tool_name, self.tool_config, http_client, self.update_folder_path,
            disable_progress=updater_setup.get('disable_progress', False),
            download_segments=updater_setup.get('download_segments', 3),
        )
        self.packer = Packer(
            tool_name, self.tool_config, self.update_folder_path,
            save_format_type=updater_setup.get('save_format_type', 'full'),
            disable_clean=updater_setup.get('disable_clean', True),
        )
        self.file_manager = FileManager(
            tool_name, self.tool_config, self.script_path,
            disable_clean=updater_setup.get('disable_clean', True),
        )
        self.script_executor = ScriptExecutor(tool_name, self.tool_config, config_manager=config_manager)

    def check_tool_installed(self):
        """
        Check if the tool is installed. Raise an exception if not found.
        """
        tool_folder_path = self.file_manager.get_tool_install_path()
        if not tool_folder_path.exists() and not self.disable_install_check:
            raise Exception(colorama.Fore.YELLOW + f'{self.tool_name}: The program was not found')

    def pre_update(self):
        """
        Execute pre-update checks and scripts.
        """
        self.check_tool_installed()
        self.script_executor.execute_script('pre_update')

    def post_update(self, scrape_data, processing_info):
        """
        Execute post-update scripts.

        :param scrape_data: Scrape data from the tool
        :param processing_info: Information about the processing step
        """
        self.config_manager.update_local_version(self.tool_name, scrape_data['download_version'])
        self.script_executor.execute_script('post_update', processing_info)
        self.script_executor.execute_global_script(processing_info)

    def download_step(self, download_url, cookies=None):
        """
        Download the tool from the given URL.

        :param download_url: URL to download the tool from
        :param cookies: Optional cookies dict from the scrape session
        :return: Path to the downloaded file
        """
        # create updates folder if don't exist
        if not self.update_folder_path.exists():
            self.update_folder_path.mkdir(parents=True)

        check_content_type = not Helpers.config_flag(self.tool_config, 'disable_content_type_check')
        return self.downloader.download_from_web(download_url, check_content_type, cookies)

    def processing_tool_step(self, file_path, download_version):
        """
        Process the downloaded tool.

        :param file_path: Path to the downloaded file
        :param download_version: Version of the downloaded tool
        :return: Dictionary containing processing information
        """
        # unpack logic
        logging.debug(f'{self.tool_name}: unpack file {file_path}')
        unpack_folder_path = self.packer.unpack_step(file_path)
        self.script_executor.execute_script(
            'post_unpack',
            {
                'tool_name': self.tool_name,
                'unpack_folder': unpack_folder_path,
                'download_version': download_version
            }
        )

        # save or repack logic
        disable_repack = Helpers.config_flag(self.tool_config, 'disable_repack')
        tool_path = self.file_manager.processing_tool_path(unpack_folder_path)
        if self.disable_repack or disable_repack:
            logging.debug(f'{self.tool_name}: repack is disabled')
            return self.file_manager.save(
                tool_folder_path=tool_path['folder_path'],
                tool_unpack_path=tool_path['unpack_path'],
            )

        logging.debug(f'{self.tool_name}: repack update')
        return self.packer.repack_step(
            tool_folder_path=tool_path['folder_path'],
            tool_unpack_path=tool_path['unpack_path'],
            version=download_version,
        )

    def cleanup_update_folder(self):
        """
        Clean up the update folder.
        """
        if self.update_folder_path.exists():
            Helpers.cleanup_folder(self.update_folder_path)

    @staticmethod
    def cleanup_updates_root():
        """
        Remove the entire updates root folder (relative to the current
        working directory, same place update_folder_path lives during a
        run). Static so callers don't need to construct a full Updater
        (5 collaborators, including a requests.Session) just to rmtree
        one folder.
        """
        updates_root = pathlib.Path(os.getcwd()) / 'updates'
        if updates_root.exists():
            Helpers.delete_folder(updates_root)

    def _is_shutdown(self):
        """Check if a shutdown has been requested."""
        return self.shutdown_event is not None and self.shutdown_event.is_set()

    def run(self):
        """
        Perform the update process for this tool.

        :return: bool: True if the update completes successfully, False if no update is needed.
        :raises Exception: If any step in the update process fails.
        """
        # execute checks and scripts
        self.pre_update()

        try:
            if self._is_shutdown():
                return False

            # generate version and download data
            logging.debug(f'{self.tool_name}: start "scrape_step"')
            scrape_data = self.scraper.scrape_step()
            if scrape_data is False:
                return False

            if self._is_shutdown():
                return False

            if self.dry_run:
                logging.info(colorama.Fore.CYAN + f'{self.tool_name}: [dry-run] update available → {scrape_data["download_version"]} ({scrape_data["download_url"]})')
                return True

            # download and process file
            logging.debug(f'{self.tool_name}: start "download_step"')
            update_file_path = self.download_step(scrape_data['download_url'], scrape_data.get('cookies'))

            if self._is_shutdown():
                return False

            logging.debug(f'{self.tool_name}: start "processing_tool_step"')
            processing_info = self.processing_tool_step(update_file_path, scrape_data['download_version'])

            if self._is_shutdown():
                return False

            # update complete
            logging.debug(f'{self.tool_name}: start "post_update"')
            self.post_update(scrape_data, processing_info)

            logging.info(f'{self.tool_name}: update complete')
            return True
        finally:
            self.cleanup_update_folder()
