import pathlib
import aiohttp
import colorama
import logging

from pypdl import Pypdl

from universal_updater.Helpers import Helpers


class Downloader:
    """Handles file downloads."""

    def __init__(self, user_agent, disable_progress, update_folder_path, download_retries=3, download_segments=3, request_timeout=30):
        """
        Initialize with optional user_agent, disable_progress flag, and update_folder_path.

        :param user_agent: User agent string for HTTP requests
        :param disable_progress: Flag to disable progress bar
        :param update_folder_path: Path to the folder where updates will be saved
        :param download_retries: Number of retry attempts on download failure
        :param download_segments: Number of segments for accelerated downloads
        :param request_timeout: Timeout in seconds for HTTP requests
        """
        self.user_agent = user_agent
        self.disable_progress = disable_progress
        self.update_folder_path = update_folder_path
        self.download_retries = download_retries
        self.download_segments = download_segments
        self.request_timeout = request_timeout
        self.tool_name = ""

    def download_file(self, url):
        """
        Download a file from a given URL using pypdl.

        :param url: URL of the file to download
        :return: Path where the file has been saved
        """
        dl = Pypdl(logger=logging.getLogger(__name__))
        result = dl.start(
            url=url,
            file_path=str(self.update_folder_path),
            segments=self.download_segments,
            display=not self.disable_progress,
            multisegment=True,
            block=True,
            retries=self.download_retries,
            overwrite=True,
            etag_validation=False,
            headers={'User-Agent': self.user_agent},
            timeout=aiohttp.ClientTimeout(total=self.request_timeout),
        )
        if dl.failed or not result:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: download failed')

        return pathlib.Path(result[0].path)

    def download_from_web(self, tool_name, download_url):
        """
        Perform a download step for a given tool.

        :param tool_name: Name of the tool
        :param download_url: URL from which to download the tool
        :return: Path where the file has been saved
        """
        self.tool_name = tool_name
        file_name = Helpers.get_filename_from_url(download_url)
        logging.info(f'{self.tool_name}: downloading update "{file_name}"')

        return self.download_file(url=download_url)
