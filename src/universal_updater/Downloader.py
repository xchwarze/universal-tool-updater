import pathlib
import aiohttp
import requests
import colorama
import logging

from pypdl import Pypdl
import pypdl_extend
from universal_updater.Helpers import Helpers


class Downloader:
    """Handles file downloads."""

    INVALID_CONTENT_TYPES = {
        'text/html',
        'text/xml',
        'application/json',
        'application/xml',
    }

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

    def validate_content_type(self, content_type):
        """
        Validate the Content-Type header to ensure the response is a downloadable file.
        Only allows known binary and archive content types.

        :param content_type: Content-Type header value from the response
        :raises Exception: If the content type is not in the whitelist
        """
        if not content_type:
            return

        mime_type = content_type.split(';')[0].strip().lower()
        if mime_type in self.INVALID_CONTENT_TYPES:
            raise Exception(
                colorama.Fore.RED + f'{self.tool_name}: invalid download, '
                f'server returned Content-Type "{mime_type}" instead of a binary or archive file'
            )

    def resolve_filename(self, url, check_content_type=True, cookies=None):
        """
        Resolve the real filename via HEAD request.
        Handles redirects and Content-Disposition headers.

        :param url: Original download URL
        :param check_content_type: Flag to validate the Content-Type header
        :param cookies: Optional cookies dict to include in the request
        :return: Resolved filename string
        """
        response = requests.head(url, headers={'User-Agent': self.user_agent},
                                         cookies=cookies, allow_redirects=True, timeout=self.request_timeout)
        response.raise_for_status()
        logging.debug("HEAD %s -> status=%s headers=%s", url, response.status_code, dict(response.headers))

        # validate Content-Type to detect invalid downloads (e.g. error pages)
        if check_content_type:
            self.validate_content_type(response.headers.get('content-type', ''))

        # try to get filename from Content-Disposition header
        content_disposition = response.headers.get('content-disposition', '')
        if 'filename=' in content_disposition:
            return content_disposition.split('filename=')[-1].strip('"; ')

        # fallback to filename from final URL (after redirects)
        return Helpers.get_filename_from_url(response.url)

    def download_file(self, url, file_name, cookies=None):
        """
        Download a file from a given URL using pypdl.

        :param url: URL of the file to download
        :param file_name: Resolved filename for the download
        :param cookies: Optional cookies dict to include in the request
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
            cookies=cookies,
            timeout=aiohttp.ClientTimeout(total=self.request_timeout),
        )

        if downloader.failed or not result:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: download failed')

        return dest_path

    def download_from_web(self, tool_name, download_url, check_content_type=True, cookies=None):
        """
        Perform a download step for a given tool.

        :param tool_name: Name of the tool
        :param download_url: URL from which to download the tool
        :param check_content_type: Flag to validate the Content-Type header
        :param cookies: Optional cookies dict to include in the request
        :return: Path where the file has been saved
        """
        self.tool_name = tool_name

        # resolve real filename (handles redirects and Content-Disposition)
        file_name = self.resolve_filename(download_url, check_content_type, cookies)
        logging.info(f'{self.tool_name}: downloading update "{file_name}"')

        return self.download_file(url=download_url, file_name=file_name, cookies=cookies)
