import re
import time
import platform
import requests
import urllib.parse
import hashlib
import colorama
import logging

from universal_updater.Helpers import Helpers


class Scraper:
    """
    Handles all scraping tasks for the Updater.
    """

    def __init__(self, force_download, use_github_api, user_agent, request_timeout=30, request_retries=3):
        """
        Initialize the Scraper with necessary configurations.

        :param use_github_api: Boolean to determine if GitHub API should be used
        :param user_agent: User agent string for HTTP requests
        :param request_timeout: Timeout in seconds for HTTP requests
        :param request_retries: Number of retry attempts on request failure
        """
        self.user_agent = user_agent
        self.force_download = force_download
        self.use_github_api = use_github_api
        self.request_timeout = request_timeout
        self.request_retries = request_retries
        self.session = requests.Session()
        self.arch_suffix = '_x64' if '64' in platform.machine() else '_x86'
        self.tool_name = ""
        self.tool_config = {}
        self.github_version_check = 'https://github.com/{0}/releases.atom'
        self.github_files = 'https://github.com/{0}/releases/expanded_assets/{1}'
        self.github_api_files = 'https://api.github.com/repos/{0}/releases/latest'
        self.scoop_manifest = 'https://raw.githubusercontent.com/ScoopInstaller/{0}/master/bucket/{1}.json'
        self.re_github_version = r'\/releases\/tag\/(\S+)"'
        self.re_github_download = '"(.*?/{0})"'

    def tool_setup(self, tool_name, tool_config):
        """
        Initialize tool-specific settings.

        :param tool_name: Name of the tool
        :param tool_config: Configuration object for the specific tool
        """
        self.tool_name = tool_name
        self.tool_config = tool_config

    def _request_with_retry(self, method_name, url, headers=None):
        """
        Performs an HTTP request with retry logic and exponential backoff.

        :param method_name: HTTP method name ('get' or 'head')
        :param url: The URL to request
        :param headers: Dictionary of HTTP headers. Defaults to {'User-Agent': self.user_agent} if not provided.
        :return: Response object
        :raises Exception: If all attempts fail
        """
        if headers is None:
            headers = {'User-Agent': self.user_agent}

        method = getattr(self.session, method_name)
        last_exception = None
        for attempt in range(self.request_retries):
            try:
                response = method(url, headers=headers, timeout=self.request_timeout, allow_redirects=True)
                response.raise_for_status()
                return response
            except Exception as exception:
                last_exception = exception
                if attempt < self.request_retries - 1:
                    wait = 2 ** attempt
                    logging.warning(f'{self.tool_name}: request failed (attempt {attempt + 1}/{self.request_retries}), retrying in {wait}s...')
                    time.sleep(wait)

        raise Exception(colorama.Fore.RED + f'{self.tool_name}: Error {last_exception}')

    def head_request(self, url, headers=None):
        """
        Performs a HEAD request to a given URL with retry logic.

        :param url: The URL to perform the HEAD request to
        :param headers: Optional dictionary containing HTTP headers.
        :return: Response object from the HEAD request
        :raises Exception: If an error occurs during the request
        """
        return self._request_with_retry('head', url, headers)

    def get_request(self, url, headers=None):
        """
        Performs a GET request to a given URL.

        :param url: The URL to perform the GET request to
        :param headers: Optional dictionary containing HTTP headers. If not provided, the default User-Agent is used.
        :return: Response object from the GET request
        :raises Exception: If an error occurs during the request
        """
        return self._request_with_retry('get', url, headers)

    def get_arch_config(self, key):
        """
        Returns the architecture-specific config value if available, falling back to the generic key.

        :param key: Base config key (e.g. 're_download', 'update_url')
        :return: Value for the arch-specific key or the generic key, or None if neither exists
        """
        return self.tool_config.get(f'{key}{self.arch_suffix}') or self.tool_config.get(key)

    #################
    # Scraper methods
    #################
    def scrape_web(self):
        """
        Scrape web for version and download URL based on tool_config.

        :return: dict|bool: A dictionary containing:
            - 'download_version' (str): Extracted version using regex.
            - 'download_url' (str): Extracted or generated download URL.
            Returns False if the version cannot be extracted.
        :raises Exception: If required configuration fields are missing or HTTP requests fail.
        """
        # load html
        url = self.tool_config.get('url', None)
        url_response = self.get_request(url)
        logging.debug(f'{self.tool_name}: HTML content fetched, starting regex matching.')

        # regex shit
        re_version = self.tool_config.get('re_version', None)
        if not re_version:
            raise Exception(colorama.Fore.RED +
                            f'{self.tool_name}: the re_version field is required for the selected mode')

        download_version = self.check_version_from_web(url_response.text, re_version)
        if download_version is None:
            return False

        download_url = self.get_download_url_from_web(url, url_response.text)
        logging.debug(f'{self.tool_name}: Regex matching done.')

        return {
            'download_version': download_version,
            'download_url': download_url,
        }

    def scrape_github(self):
        """
        Scrape GitHub for version and download URL based on tool_config.

        :return: dict|bool: A dictionary containing:
            - 'download_version' (str): Extracted version from GitHub.
            - 'download_url' (str): The determined or generated download URL.
            Returns False if the version cannot be extracted.
        :raises Exception: If required configuration fields are missing or HTTP requests fail.
        """
        if self.use_github_api:
            return self.scrape_github_api()

        github_repo = self.tool_config.get('url', None)

        # load html
        version_url = self.github_version_check.format(github_repo)
        version_response = self.get_request(version_url)
        logging.debug(f'{self.tool_name}: Version HTML fetched, starting regex matching for version.')

        download_version = self.check_version_from_web(version_response.text, self.re_github_version)
        if download_version is None:
            return False

        logging.debug(f'{self.tool_name}: Regex matching for version done.')

        # the download url is not configured, so I have to generate one.
        update_url = self.get_arch_config('update_url')
        if not update_url:
            logging.debug(f'{self.tool_name}: update_url not set. I try to generate it.')
            download_url = self.github_files.format(github_repo, download_version)
            update_url = self.get_download_url_from_github(download_url)

        return {
            'download_version': download_version,
            'download_url': update_url,
        }

    def scrape_github_api(self):
        """
        Scrape GitHub API for version and download URL based on tool_config.

        :return: dict|bool: A dictionary containing:
            - 'download_version' (str): Extracted version from the API response.
            - 'download_url' (str): The determined or generated download URL.
            Returns False if the version cannot be extracted.
        :raises Exception: If the API request fails or the response is invalid.
        """
        logging.debug(f'{self.tool_name}: Consuming GitHub via Api')
        github_repo = self.tool_config.get('url', None)
        repo_url = self.github_api_files.format(github_repo)

        # load json
        headers = {'Authorization': f'token {self.use_github_api}'}
        api_response = self.get_request(repo_url, headers)
        json_response = api_response.json()
        logging.debug(f'{self.tool_name}: JSON fetched, extracting version and download URL.')

        update_url = self.get_arch_config('update_url')
        if not update_url:
            logging.debug(f'{self.tool_name}: update_url not set. I try to generate it.')
            update_url = self.get_download_url_from_github_api(json_response)

        download_version = self.check_version_from_github_api(json_response)
        if download_version is None:
            return False

        logging.debug(f'{self.tool_name}: Version and download URL extracted.')

        # regex shit
        return {
            'download_version': download_version,
            'download_url': update_url,
        }

    def scrape_http(self):
        """
        Scrape HTTP headers for version based on tool_config.

        :return: dict|bool: A dictionary containing:
            - 'download_version' (str): Extracted version from the headers.
            - 'download_url' (str): The update URL.
            Returns False if the version cannot be extracted.
        :raises Exception: If 'update_url' is missing or an HTTP error occurs.
        """
        # get http response
        update_url = self.get_arch_config('update_url')
        if not update_url:
            raise Exception(colorama.Fore.RED +
                            f'{self.tool_name}: the update_url field is required for the selected mode')

        http_response = self.head_request(update_url)
        logging.debug(f'{self.tool_name}: HTTP headers fetched, extracting version.')

        download_version = self.check_version_from_http(http_response.headers)
        if download_version is None:
            return False

        logging.debug(f'{self.tool_name}: Version extracted.')

        return {
            'download_version': download_version,
            'download_url': update_url,
        }

    def scrape_scoop(self):
        """
        Scrape a Scoop bucket manifest for version and download URL.

        :return: dict|bool: A dictionary containing:
            - 'download_version' (str): Version from the manifest.
            - 'download_url' (str): Resolved download URL.
            Returns False if already up to date.
        :raises Exception: If the manifest is missing required fields.
        """
        app = self.tool_config.get('url', None)
        bucket = self.tool_config.get('scoop_bucket', 'main').capitalize()
        force_x86 = self.tool_config.get('force_x86', 'false').lower() == 'true'

        manifest_url = self.scoop_manifest.format(bucket, app)
        logging.debug(f'{self.tool_name}: fetching scoop manifest from {manifest_url}')
        response = self.get_request(manifest_url)
        manifest = response.json()

        version = manifest.get('version')
        if not version:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: no version found in scoop manifest')

        version = self._compare_version(version)
        if version is None:
            return False

        arch_key = '32bit' if (force_x86 or self.arch_suffix == '_x86') else '64bit'
        arch_url = manifest.get('architecture', {}).get(arch_key, {}).get('url')
        download_url = arch_url or manifest.get('url')

        if not download_url:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: no download URL found in scoop manifest')

        if isinstance(download_url, list):
            download_url = download_url[0]

        return {
            'download_version': version,
            'download_url': download_url,
        }

    #################
    # Check methods
    #################
    def _compare_version(self, remote_version):
        """
        Compare remote_version against the tool's local_version and log the
        outcome.

        :param remote_version: The version extracted from the remote source
        :return: None if already up to date (unless force_download), otherwise remote_version unchanged
        """
        local_version = self.tool_config.get('local_version', '0')
        if not self.force_download and local_version == remote_version:
            logging.info(f'{self.tool_name}: {local_version} is the latest version')
            return None

        logging.info(f'{self.tool_name}: updated from {local_version} --> {remote_version}')

        return remote_version

    def check_version_from_web(self, html, re_version):
        """
        Check version from web HTML content.

        :param html: HTML content
        :param re_version: Regex pattern for version
        :return: Version string
        """
        html_regex_version = re.findall(re_version, html)

        if not html_regex_version:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: re_version regex not match ({re_version})')

        return self._compare_version(html_regex_version[0])

    def check_version_from_http(self, headers):
        """
        Check version from HTTP headers.

        :param headers: HTTP headers
        :return: Version string (SHA-1 based)
        """
        for header in ('last-modified', 'content-length'):
            if header in headers:
                logging.debug(f'{self.tool_name}: using "{header}" as version number')
                return self._compare_version(hashlib.sha1(headers[header].encode()).hexdigest())

        raise Exception(colorama.Fore.RED +
                        f'{self.tool_name}: no header is found with which to determine if there is an update')

    def check_version_from_github_api(self, json):
        """
        Check version from GitHub API JSON response.

        :param json: JSON response from GitHub API
        :return: Version string
        """
        tag_name = json.get('tag_name')
        if not tag_name:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: "tag_name" not found in GitHub API response')

        return self._compare_version(tag_name)

    #################
    # Download url methods
    #################
    def get_download_url_from_web(self, url, response_html):
        """
        Get download URL from a web page using regex.

        :param url: Original URL of the web page
        :param response_html: HTML content of the web page
        :return: Download URL found or None
        """
        re_download = self.get_arch_config('re_download')
        update_url = self.get_arch_config('update_url')

        # case 2: if update_url is not set, scrape the link from html
        if re_download:
            html_regex_download = re.findall(re_download, response_html)
            if not html_regex_download:
                # case 4: use update_url as regex target
                if not update_url:
                    raise Exception(colorama.Fore.RED + f'{self.tool_name}: re_download regex not match ({re_download})')

                logging.debug(f'{self.tool_name}: Testing combination of update_url and re_download.')
                update_url_response = self.get_request(update_url)
                html_regex_download = re.findall(re_download, update_url_response.text)
                if not html_regex_download:
                    raise Exception(colorama.Fore.RED + f'{self.tool_name}: re_download regex not match ({re_download})')

            # case 1: generated link is valid
            if Helpers.is_valid_url(html_regex_download[0]):
                return html_regex_download[0]

            # case 2: fix generated link
            if update_url:
                # fix from configured path
                update_url = f'{update_url}{html_regex_download[0]}'
            else:
                # fix from original url path
                url_parse_fix = urllib.parse.urlparse(url)
                update_url = f'{url_parse_fix.scheme}://{url_parse_fix.netloc}/{html_regex_download[0]}'

        # case 3: if only update_url is set... download it!
        if not update_url:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: update_url not generated!')

        return update_url

    def get_download_url_from_github(self, download_url):
        """
        Get download URL from a github release page using regex.

        :param download_url: Base URL for download
        :return: Download URL found or None
        """
        re_download = self.get_arch_config('re_download')
        if not re_download:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: re_download not set!')

        download_response = self.get_request(download_url)
        fixed_re_download = self.re_github_download.format(re_download)
        html_regex_download = re.findall(fixed_re_download, download_response.text)
        if not html_regex_download:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: re_download regex not match ({re_download})')

        download_url_parse = urllib.parse.urlparse(download_url)
        update_url = f'{download_url_parse.scheme}://{download_url_parse.netloc}/{html_regex_download[0]}'

        return update_url

    def get_download_url_from_github_api(self, json):
        """
        Get download URL from GitHub API JSON response.

        :param json: JSON response from GitHub API
        :return: Download URL found or None
        """
        re_download = self.get_arch_config('re_download')
        if not re_download:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: re_download regex not set')

        assets = json.get('assets')
        if assets is None:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: "assets" not found in GitHub API response')

        update_url = None
        for attachment in assets:
            html_regex_download = re.findall(re_download, attachment['browser_download_url'])
            if html_regex_download:
                update_url = attachment['browser_download_url']
                break

        if not update_url:
            raise Exception(colorama.Fore.RED + f'{self.tool_name}: re_download regex not match ({re_download})')

        return update_url

    #################
    # Scrape step
    #################
    def scrape_step(self):
        """
        Execute a specific script for a given tool based on tool_config.

        :return: Dictionary containing 'download_version', 'download_url' and 'cookies'
        """
        from_url = self.tool_config.get('from', 'web')
        if from_url == 'github':
            result = self.scrape_github()
        elif from_url == 'http':
            result = self.scrape_http()
        elif from_url == 'scoop':
            result = self.scrape_scoop()
        else:
            result = self.scrape_web()

        if result:
            result['cookies'] = self._collect_cookies_for(result.get('download_url', ''))

        return result

    def _collect_cookies_for(self, url):
        """
        Build a plain cookie dict scoped to the given URL's host, so a later
        request to the download URL only receives cookies that actually belong
        to it — avoids both CookieConflictError (duplicate names across domains
        in self.session.cookies) and leaking unrelated-domain session cookies
        to the download host.

        :param url: The URL the cookies will be sent to
        :return: Dictionary of cookie name/value pairs scoped to the URL's host
        """
        if not url:
            return {}

        target_host = urllib.parse.urlparse(url).hostname or ''
        cookies = {}
        for cookie in self.session.cookies:
            cookie_domain = (cookie.domain or '').lstrip('.')
            if cookie_domain and target_host != cookie_domain and not target_host.endswith('.' + cookie_domain):
                continue
            cookies[cookie.name] = cookie.value

        return cookies
