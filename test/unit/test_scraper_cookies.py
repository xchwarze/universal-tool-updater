"""
Unit tests for Scraper._collect_cookies_for.

Regression covered: a single requests.Session can accumulate cookies with the
SAME name but DIFFERENT domains (e.g. a tracking cookie set by the scraped
page's own domain, plus one set by a redirect through a CDN). Calling
dict(session.cookies) in that situation raises CookieConflictError.
_collect_cookies_for must never do that, and must scope cookies to the
target download host (with subdomain matching), not just dump everything.
"""

import pytest
import requests
from requests.cookies import CookieConflictError

from universal_updater.HttpClient import HttpClient
from universal_updater.Scraper import Scraper


def make_scraper():
    http_client = HttpClient(tool_name='Tool', user_agent='test-agent')
    return Scraper('Tool', {}, http_client)


def test_dict_session_cookies_raises_on_duplicate_name_different_domains():
    # This documents the bug _collect_cookies_for exists to avoid.
    session = requests.Session()
    session.cookies.set('session_id', 'aaa', domain='example.com')
    session.cookies.set('session_id', 'bbb', domain='unrelated.com')

    with pytest.raises(CookieConflictError):
        dict(session.cookies)


def test_collect_cookies_for_does_not_raise_on_duplicate_names():
    scraper = make_scraper()
    scraper.http_client.session.cookies.set('session_id', 'aaa', domain='example.com')
    scraper.http_client.session.cookies.set('session_id', 'bbb', domain='unrelated.com')

    # must not raise CookieConflictError
    cookies = scraper._collect_cookies_for('https://example.com/file.zip')

    assert cookies == {'session_id': 'aaa'}


def test_collect_cookies_for_scopes_to_subdomain():
    scraper = make_scraper()
    scraper.http_client.session.cookies.set('session_id', 'aaa', domain='example.com')
    scraper.http_client.session.cookies.set('session_id', 'bbb', domain='unrelated.com')

    # download.example.com should inherit the example.com cookie...
    cookies = scraper._collect_cookies_for('https://download.example.com/file.zip')

    assert cookies == {'session_id': 'aaa'}


def test_collect_cookies_for_excludes_unrelated_domain():
    scraper = make_scraper()
    scraper.http_client.session.cookies.set('token', 'xyz', domain='unrelated.com')

    # ...but a completely unrelated domain's cookie must never leak through
    cookies = scraper._collect_cookies_for('https://download.example.com/file.zip')

    assert cookies == {}


def test_collect_cookies_for_exact_host_match():
    scraper = make_scraper()
    scraper.http_client.session.cookies.set('token', 'xyz', domain='example.com')

    cookies = scraper._collect_cookies_for('https://example.com/file.zip')

    assert cookies == {'token': 'xyz'}


def test_collect_cookies_for_does_not_match_unrelated_suffix():
    # 'notexample.com' shares a suffix with 'example.com' but is a different
    # registrable domain - must not be treated as a subdomain match.
    scraper = make_scraper()
    scraper.http_client.session.cookies.set('token', 'xyz', domain='example.com')

    cookies = scraper._collect_cookies_for('https://download.notexample.com/file.zip')

    assert cookies == {}


def test_collect_cookies_for_empty_url_returns_empty_dict():
    scraper = make_scraper()
    scraper.http_client.session.cookies.set('token', 'xyz', domain='example.com')

    assert scraper._collect_cookies_for('') == {}


def test_collect_cookies_for_host_only_cookie_has_no_domain_restriction():
    # A cookie set with no explicit domain has cookie.domain == '' and is
    # treated as unscoped (not filtered out) by the domain check.
    scraper = make_scraper()
    scraper.http_client.session.cookies.set('nodomain', 'v')

    cookies = scraper._collect_cookies_for('https://anything.example.org/x')

    assert cookies == {'nodomain': 'v'}
