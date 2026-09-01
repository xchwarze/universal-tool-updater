"""
Unit tests for ConfigManager: UTF-8 persistence and atomic-write safety.
"""

import configparser

import pytest

from universal_updater.ConfigManager import ConfigManager


def test_utf8_value_round_trips_through_disk(tmp_path):
    config_file = tmp_path / 'tools.ini'
    cm = ConfigManager(str(config_file))

    value = 'Café Ñoño 日本語 update ★'
    cm.set_config('ToolA', 'display_name', value)

    # re-read with a *fresh* instance to prove it was actually persisted
    # (and re-decoded) correctly as UTF-8, not just cached in memory.
    cm_reloaded = ConfigManager(str(config_file))
    assert cm_reloaded.get_config('ToolA', 'display_name') == value

    # the file on disk must be valid UTF-8 and contain the literal value
    text = config_file.read_text(encoding='utf-8')
    assert value in text


def test_write_config_is_atomic_on_failure(tmp_path, monkeypatch):
    config_file = tmp_path / 'tools.ini'
    cm = ConfigManager(str(config_file))

    # establish a known-good baseline on disk
    cm.set_config('ToolA', 'local_version', '1.0.0')
    original_bytes = config_file.read_bytes()

    def raising_write(self, fp, space_around_delimiters=True):
        # simulate a failure partway through writing, after some bytes
        # have already gone out to the (temp) file handle
        fp.write('[ToolA]\n')
        raise RuntimeError('simulated write failure')

    monkeypatch.setattr(configparser.ConfigParser, 'write', raising_write)

    with pytest.raises(RuntimeError):
        cm.set_config('ToolA', 'local_version', '2.0.0')

    # the original file must be completely unchanged, byte for byte
    assert config_file.read_bytes() == original_bytes

    # and no leftover .tmp file should remain in the directory
    remaining_names = {p.name for p in tmp_path.iterdir()}
    assert remaining_names == {'tools.ini'}


def test_write_config_leaves_no_tmp_file_on_success(tmp_path):
    config_file = tmp_path / 'tools.ini'
    cm = ConfigManager(str(config_file))

    cm.set_config('ToolA', 'local_version', '1.0.0')

    remaining_names = {p.name for p in tmp_path.iterdir()}
    assert remaining_names == {'tools.ini'}
