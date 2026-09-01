import pathlib
import aiohttp
import colorama
import logging

from email.message import Message

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

    def __init__(self, tool_name, tool_config, http_client, update_folder_path, disable_progress=False, download_segments=3):
        """
        Initialize the Downloader.

        :param tool_name: Name of the tool
        :param tool_config: Configuration dict for the tool
        :param http_client: Shared HttpClient (session + retry-with-backoff + User-Agent)
        :param update_folder_path: Path to the folder where updates will be saved
        :param disable_progress: Flag to disable progress bar
        :param download_segments: Number of segments for accelerated downloads
        """
        self.tool_name = tool_name
        self.tool_config = tool_config
        self.http_client = http_client
        self.update_folder_path = update_folder_path
        self.disable_progress = disable_progress
        self.download_segments = download_segments

    def validate_content_type(self, content_type):
        """
        Validate the Content-Type header to ensure the response is a downloadable file.
        Rejects known non-binary content types (e.g. an HTML error page); anything
        else is allowed through.

        :param content_type: Content-Type header value from the response
        :raises Exception: If the content type is in INVALID_CONTENT_TYPES
        """
        if not content_type:
            return

        mime_type = content_type.split(';')[0].strip().lower()
        if mime_type in self.INVALID_CONTENT_TYPES:
            raise Exception(
                colorama.Fore.RED + f'{self.tool_name}: invalid download, '
                f'server returned Content-Type "{mime_type}" instead of a binary or archive file'
            )

    def resolve_filename(self, url, check_content_type=True):
        """
        Resolve the real filename via HEAD request.
        Handles redirects and Content-Disposition headers.

        :param url: Original download URL
        :param check_content_type: Flag to validate the Content-Type header
        :return: Resolved filename string
        """
        # no explicit cookies= here: this HEAD goes through the same shared
        # HttpClient session that already scraped this tool, so the jar
        # already has what's needed - passing the scraped cookie dict again
        # would duplicate every cookie in the Cookie header (requests merges
        # both sources)
        response = self.http_client.head(url)
        logging.debug("HEAD %s -> status=%s headers=%s", url, response.status_code, dict(response.headers))

        # validate Content-Type to detect invalid downloads (e.g. error pages)
        if check_content_type:
            self.validate_content_type(response.headers.get('content-type', ''))

        # try to get filename from Content-Disposition header
        filename = None
        content_disposition = response.headers.get('content-disposition', '')
        if content_disposition:
            msg = Message()
            msg['content-disposition'] = content_disposition
            filename = msg.get_filename()
            if filename:
                # strip any directory components to prevent path traversal
                filename = pathlib.Path(filename).name

        # fallback to filename from final URL (after redirects)
        if not filename:
            filename = Helpers.get_filename_from_url(response.url)

        # an empty name would make dest_path resolve to update_folder_path itself
        # (a shared directory), corrupting unrelated in-flight downloads/unpacks
        if not filename:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: could not determine a filename for the download')

        return filename

    def download_file(self, url, file_name, cookies=None):
        """
        Download a file from a given URL using pypdl.

        :param url: URL of the file to download
        :param file_name: Resolved filename for the download
        :param cookies: Optional cookies dict to include in the request
        :return: Path where the file has been saved
        """
        dest_path = pathlib.Path(self.update_folder_path).joinpath(file_name)
        self._clear_stale_download_state(dest_path)

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
            retries=self.http_client.request_retries,
            overwrite=True,
            etag_validation=False,
            headers={'User-Agent': self.http_client.user_agent},
            cookies=cookies,
            timeout=aiohttp.ClientTimeout(total=self.http_client.request_timeout),
        )

        if downloader.failed or not result:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: download failed')

        return dest_path

    def _clear_stale_download_state(self, dest_path):
        """
        Remove any pypdl progress/segment files left over from a previous aborted
        run for this exact destination. pypdl runs here with etag_validation=False,
        so it will otherwise trust a leftover "<file>.json" progress record blindly
        and resume-append onto stale/partial segment files instead of starting
        fresh — this app never intends to resume a download across invocations.
        """
        if not dest_path.parent.exists():
            return

        prefix = dest_path.name + '.'
        for sibling in dest_path.parent.iterdir():
            if sibling.is_file() and sibling.name.startswith(prefix):
                sibling.unlink()

    def download_from_web(self, download_url, check_content_type=True, cookies=None):
        """
        Perform a download step for this tool.

        :param download_url: URL from which to download the tool
        :param check_content_type: Flag to validate the Content-Type header
        :param cookies: Optional cookies dict to include in the request
        :return: Path where the file has been saved
        """
        # resolve real filename (handles redirects and Content-Disposition)
        file_name = self.resolve_filename(download_url, check_content_type)
        logging.info(f'{self.tool_name}: downloading update "{file_name}"')

        return self.download_file(url=download_url, file_name=file_name, cookies=cookies)
