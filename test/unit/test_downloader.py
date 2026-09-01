"""
Unit tests for Downloader._clear_stale_download_state and resolve_filename.

resolve_filename normally does a real HTTP HEAD via the shared HttpClient;
here it is exercised with a lightweight fake response object (just
`.headers`, `.url`, `.status_code`, `.raise_for_status()`) via monkeypatching
the HttpClient's own requests.Session, so no network is involved.
"""

import pytest

from universal_updater.Downloader import Downloader
from universal_updater.HttpClient import HttpClient


def make_downloader(update_folder_path, tool_config=None):
    http_client = HttpClient(tool_name='Tool', user_agent='test-agent')
    return Downloader('Tool', tool_config or {}, http_client, str(update_folder_path), disable_progress=True)


class FakeHeadResponse:
    """Minimal stand-in for a requests.Response, as returned by HttpClient.head()."""

    def __init__(self, headers=None, url='https://example.com/download/file.zip'):
        self.headers = headers or {}
        self.url = url
        self.status_code = 200

    def raise_for_status(self):
        pass


# ---------------------------------------------------------------------------
# _clear_stale_download_state
# ---------------------------------------------------------------------------

def test_clear_stale_download_state_removes_stale_siblings(tmp_path):
    downloader = make_downloader(tmp_path)
    dest_path = tmp_path / 'tool.zip'

    stale_json = tmp_path / 'tool.zip.json'
    stale_seg0 = tmp_path / 'tool.zip.0'
    stale_seg1 = tmp_path / 'tool.zip.1'
    unrelated = tmp_path / 'othertool.zip.json'
    for stale_file in (stale_json, stale_seg0, stale_seg1, unrelated):
        stale_file.write_text('data')

    downloader._clear_stale_download_state(dest_path)

    assert not stale_json.exists()
    assert not stale_seg0.exists()
    assert not stale_seg1.exists()
    assert unrelated.exists()


def test_clear_stale_download_state_noop_when_nothing_stale(tmp_path):
    downloader = make_downloader(tmp_path)
    dest_path = tmp_path / 'tool.zip'
    unrelated = tmp_path / 'unrelated.txt'
    unrelated.write_text('data')

    # nothing matches the "tool.zip." prefix - must not raise, must not touch it
    downloader._clear_stale_download_state(dest_path)

    assert unrelated.exists()


def test_clear_stale_download_state_noop_when_parent_missing(tmp_path):
    downloader = make_downloader(tmp_path)
    dest_path = tmp_path / 'missing_dir' / 'tool.zip'

    # parent directory doesn't even exist yet - must not raise
    downloader._clear_stale_download_state(dest_path)


# ---------------------------------------------------------------------------
# resolve_filename
# ---------------------------------------------------------------------------

def test_resolve_filename_prefers_plain_filename_over_filename_star(tmp_path, monkeypatch):
    downloader = make_downloader(tmp_path)
    response = FakeHeadResponse(headers={
        'content-disposition': 'attachment; filename="good.zip"; filename*=UTF-8\'\'good-alt.zip',
    })
    monkeypatch.setattr(downloader.http_client.session, 'head', lambda *args, **kwargs: response)

    filename = downloader.resolve_filename('https://example.com/download')

    assert filename == 'good.zip'


def test_resolve_filename_defuses_path_traversal(tmp_path, monkeypatch):
    downloader = make_downloader(tmp_path)
    response = FakeHeadResponse(headers={
        'content-disposition': 'attachment; filename="../../evil.zip"',
    })
    monkeypatch.setattr(downloader.http_client.session, 'head', lambda *args, **kwargs: response)

    filename = downloader.resolve_filename('https://example.com/download')

    assert filename == 'evil.zip'
    assert '..' not in filename
    assert '/' not in filename
    assert '\\' not in filename


def test_resolve_filename_falls_back_to_url_when_no_content_disposition(tmp_path, monkeypatch):
    downloader = make_downloader(tmp_path)
    response = FakeHeadResponse(headers={}, url='https://example.com/files/tool-v1.2.3.zip')
    monkeypatch.setattr(downloader.http_client.session, 'head', lambda *args, **kwargs: response)

    filename = downloader.resolve_filename('https://example.com/download')

    assert filename == 'tool-v1.2.3.zip'


def test_resolve_filename_rejects_invalid_content_type(tmp_path, monkeypatch):
    downloader = make_downloader(tmp_path)
    response = FakeHeadResponse(headers={'content-type': 'text/html; charset=utf-8'})
    monkeypatch.setattr(downloader.http_client.session, 'head', lambda *args, **kwargs: response)

    with pytest.raises(Exception):
        downloader.resolve_filename('https://example.com/download')


def test_resolve_filename_raises_on_empty_resolved_filename(tmp_path, monkeypatch):
    # Content-Disposition collapses to "" (pathlib.Path("/").name == "") AND the
    # final URL has no path component either (Helpers.get_filename_from_url also
    # returns ""), so both fallbacks are exhausted -> must raise, not silently
    # return "" (an empty name would make dest_path resolve to update_folder_path
    # itself, a shared directory, corrupting unrelated in-flight downloads).
    downloader = make_downloader(tmp_path)
    response = FakeHeadResponse(
        headers={'content-disposition': 'attachment; filename="/"'},
        url='https://example.com',
    )
    monkeypatch.setattr(downloader.http_client.session, 'head', lambda *args, **kwargs: response)

    with pytest.raises(Exception):
        downloader.resolve_filename('https://example.com/download')
