import pathlib
import aiohttp
import requests
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

    def resolve_filename(self, url):
        """
        Resolve the real filename via HEAD request.
        Handles redirects and Content-Disposition headers.

        :param url: Original download URL
        :return: Resolved filename string
        """
        try:
            response = self.session.head(url, headers={'User-Agent': self.user_agent},
                                         allow_redirects=True, timeout=self.request_timeout)
            response.raise_for_status()

            # try to get filename from Content-Disposition header
            content_disposition = response.headers.get('content-disposition', '')
            if 'filename=' in content_disposition:
                return content_disposition.split('filename=')[-1].strip('"; ')

            # fallback to filename from final URL (after redirects)
            return Helpers.get_filename_from_url(response.url)
        except Exception:
            # HEAD not supported, fall back to URL parsing
            return Helpers.get_filename_from_url(url)

    def download_file(self, url, file_name):
        """
        Download a file from a given URL using pypdl.

        :param url: URL of the file to download
        :param file_name: Resolved filename for the download
        :return: Path where the file has been saved
        """
        dest_path = pathlib.Path(self.update_folder_path).joinpath(file_name)

        # create a logger adapter to prefix pypdl messages with the tool name
        # this propagates to the root logger, so ColoredFormatter applies automatically
        logger = logging.LoggerAdapter(
            logging.getLogger('downloader'),
            {'tool_name': self.tool_name}
        )
        logger.process = lambda msg, kwargs: (f'{self.tool_name}: {msg}', kwargs)

        downloader = Pypdl(logger=logger)
        result = downloader.start(
            url=url,
            file_path=str(dest_path),
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

        if downloader.failed or not result:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: download failed')

        return dest_path

    def download_from_web(self, tool_name, download_url):
        """
        Perform a download step for a given tool.

        :param tool_name: Name of the tool
        :param download_url: URL from which to download the tool
        :return: Path where the file has been saved
        """
        self.tool_name = tool_name

        # resolve real filename (handles redirects and Content-Disposition)
        file_name = self.resolve_filename(download_url)
        logging.info(f'{self.tool_name}: downloading update "{file_name}"')

        return self.download_file(url=download_url, file_name=file_name)
