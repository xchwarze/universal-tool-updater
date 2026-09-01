"""
Unit tests for Updater's single-construction behavior: the shared HttpClient
wiring, and that construction raises cleanly for an unknown tool name.
"""

import pytest

from universal_updater.ConfigManager import ConfigManager
from universal_updater.Updater import Updater


def make_config_manager(tmp_path, tool_name='TestTool', extra_lines=''):
    ini_path = tmp_path / 'tools.ini'
    ini_path.write_text(f'[{tool_name}]\nfolder = tools\\{tool_name}\n{extra_lines}', encoding='utf-8')
    return ConfigManager(str(ini_path))


def test_scraper_and_downloader_share_one_http_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_manager = make_config_manager(tmp_path)

    updater = Updater(config_manager=config_manager, tool_name='TestTool')

    assert updater.scraper.http_client is updater.downloader.http_client
    assert updater.scraper.http_client.session is updater.downloader.http_client.session


def test_unknown_tool_name_raises_at_construction(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_manager = make_config_manager(tmp_path, tool_name='RealTool')

    with pytest.raises(Exception):
        Updater(config_manager=config_manager, tool_name='NoSuchTool')
