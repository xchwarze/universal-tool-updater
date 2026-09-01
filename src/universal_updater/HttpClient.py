import time
import colorama
import logging
import requests


class HttpClient:
    """
    Shared HTTP layer (one requests.Session + retry-with-backoff) used by
    both Scraper and Downloader, one instance per Updater/tool.
    """

    def __init__(self, tool_name, user_agent, request_timeout=30, request_retries=3):
        """
        :param tool_name: Name of the tool, used to prefix retry log messages
        :param user_agent: Default User-Agent header for requests
        :param request_timeout: Timeout in seconds for HTTP requests
        :param request_retries: Number of retry attempts on request failure
        """
        self.tool_name = tool_name
        self.user_agent = user_agent
        self.request_timeout = request_timeout
        self.request_retries = request_retries
        self.session = requests.Session()

    def get(self, url, headers=None, cookies=None):
        """
        Performs a GET request with retry logic.

        :param url: The URL to perform the GET request to
        :param headers: Optional dictionary of HTTP headers. Defaults to {'User-Agent': self.user_agent}.
        :param cookies: Optional cookies dict to include in the request
        :return: Response object
        :raises Exception: If all attempts fail
        """
        return self._request_with_retry('get', url, headers, cookies)

    def head(self, url, headers=None, cookies=None):
        """
        Performs a HEAD request with retry logic.

        :param url: The URL to perform the HEAD request to
        :param headers: Optional dictionary of HTTP headers. Defaults to {'User-Agent': self.user_agent}.
        :param cookies: Optional cookies dict to include in the request
        :return: Response object
        :raises Exception: If all attempts fail
        """
        return self._request_with_retry('head', url, headers, cookies)

    def _request_with_retry(self, method_name, url, headers=None, cookies=None):
        """
        Performs an HTTP request with retry logic and exponential backoff.

        :param method_name: HTTP method name ('get' or 'head')
        :param url: The URL to request
        :param headers: Dictionary of HTTP headers. Defaults to {'User-Agent': self.user_agent} if not provided.
        :param cookies: Optional cookies dict to include in the request
        :return: Response object
        :raises Exception: If all attempts fail
        """
        if headers is None:
            headers = {'User-Agent': self.user_agent}

        method = getattr(self.session, method_name)
        last_exception = None
        for attempt in range(self.request_retries):
            try:
                response = method(url, headers=headers, cookies=cookies, timeout=self.request_timeout, allow_redirects=True)
                response.raise_for_status()
                return response
            except Exception as exception:
                last_exception = exception
                if attempt < self.request_retries - 1:
                    wait = 2 ** attempt
                    logging.warning(f'{self.tool_name}: request failed (attempt {attempt + 1}/{self.request_retries}), retrying in {wait}s...')
                    time.sleep(wait)

        raise Exception(colorama.Fore.RED + f'{self.tool_name}: Error {last_exception}')
