"""
Unit tests for Helpers.cleanup_folder.
"""

import os
import stat

from universal_updater.Helpers import Helpers


def test_cleanup_folder_removes_readonly_file_without_raising(tmp_path):
    target = tmp_path / 'readonly.txt'
    target.write_text('data')
    os.chmod(target, stat.S_IREAD)

    Helpers.cleanup_folder(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_cleanup_folder_removes_nested_subdirectory(tmp_path):
    subdir = tmp_path / 'nested'
    subdir.mkdir()
    (subdir / 'inner.txt').write_text('data')
    deeper = subdir / 'deeper'
    deeper.mkdir()
    (deeper / 'file.txt').write_text('more data')

    Helpers.cleanup_folder(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_cleanup_folder_removes_readonly_file_inside_subdirectory(tmp_path):
    subdir = tmp_path / 'nested'
    subdir.mkdir()
    readonly_file = subdir / 'readonly.txt'
    readonly_file.write_text('data')
    os.chmod(readonly_file, stat.S_IREAD)

    # shutil.rmtree would normally raise PermissionError here without the
    # onerror handler clearing the read-only attribute and retrying
    Helpers.cleanup_folder(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_cleanup_folder_leaves_the_folder_itself_intact(tmp_path):
    (tmp_path / 'a.txt').write_text('data')

    Helpers.cleanup_folder(tmp_path)

    assert tmp_path.exists()
    assert list(tmp_path.iterdir()) == []
