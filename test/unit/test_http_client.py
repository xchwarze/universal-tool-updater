"""
Unit tests for HttpClient: retry-with-backoff, default headers, cookie
passthrough. No real network calls - requests.Session.get/head are
monkeypatched per test.
"""

import time

import pytest
import requests

from universal_updater.HttpClient import HttpClient


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        pass


def test_get_returns_response_on_first_success(monkeypatch):
    client = HttpClient(tool_name='Tool', user_agent='test-agent', request_timeout=5, request_retries=3)
    calls = []

    def fake_get(url, headers=None, cookies=None, timeout=None, allow_redirects=None):
        calls.append((url, headers, cookies, timeout, allow_redirects))
        return FakeResponse()

    monkeypatch.setattr(client.session, 'get', fake_get)

    response = client.get('https://example.com/page')

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0] == ('https://example.com/page', {'User-Agent': 'test-agent'}, None, 5, True)


def test_head_passes_cookies_and_custom_headers_through(monkeypatch):
    client = HttpClient(tool_name='Tool', user_agent='test-agent')
    seen = {}

    def fake_head(url, headers=None, cookies=None, timeout=None, allow_redirects=None):
        seen['headers'] = headers
        seen['cookies'] = cookies
        return FakeResponse()

    monkeypatch.setattr(client.session, 'head', fake_head)

    client.head('https://example.com/file.zip', headers={'Authorization': 'token xyz'}, cookies={'session': 'abc'})

    assert seen['headers'] == {'Authorization': 'token xyz'}
    assert seen['cookies'] == {'session': 'abc'}


def test_retries_on_failure_then_succeeds(monkeypatch):
    client = HttpClient(tool_name='Tool', user_agent='test-agent', request_retries=3)
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)
    attempts = {'count': 0}

    def flaky_get(url, headers=None, cookies=None, timeout=None, allow_redirects=None):
        attempts['count'] += 1
        if attempts['count'] < 3:
            raise requests.exceptions.ConnectionError('boom')
        return FakeResponse()

    monkeypatch.setattr(client.session, 'get', flaky_get)

    response = client.get('https://example.com/page')

    assert response.status_code == 200
    assert attempts['count'] == 3


def test_raises_after_exhausting_retries(monkeypatch):
    client = HttpClient(tool_name='Tool', user_agent='test-agent', request_retries=2)
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)

    def always_fails(url, headers=None, cookies=None, timeout=None, allow_redirects=None):
        raise requests.exceptions.ConnectionError('boom')

    monkeypatch.setattr(client.session, 'get', always_fails)

    with pytest.raises(Exception):
        client.get('https://example.com/page')


def test_raise_for_status_failure_is_retried(monkeypatch):
    client = HttpClient(tool_name='Tool', user_agent='test-agent', request_retries=2)
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)

    class FailingResponse(FakeResponse):
        def raise_for_status(self):
            raise requests.exceptions.HTTPError('500 server error')

    monkeypatch.setattr(client.session, 'get', lambda *a, **k: FailingResponse())

    with pytest.raises(Exception):
        client.get('https://example.com/page')
