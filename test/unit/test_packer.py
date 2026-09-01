"""
Unit tests for Packer.repack_merge and Packer.repack_step.

These cover the actual regressions fixed in this session's code review
(see git history: c6c2fc3 "Fix merge deleting old version before final
move" and 167e335 "Fix repack temp archive path collision between
parallel tools") for the specific case where the downloaded archive has
no single wrapping folder, so FileManager.processing_tool_path leaves
tool_unpack_path == update_folder_path / unpack_folder_path.
"""

import pathlib
import shutil
import tempfile

import py7zr
import pytest

from universal_updater.Packer import Packer


def make_packer(update_folder_path, tool_name='ToolX', tool_config=None,
                 save_format_type='full', disable_clean=False):
    packer = Packer(
        update_folder_path=str(update_folder_path),
        save_format_type=save_format_type,
        disable_clean=disable_clean,
    )
    packer.tool_setup(tool_name, tool_config if tool_config is not None else {})
    return packer


def build_7z(archive_path, files):
    """Build a real .7z archive at archive_path containing `files`
    (mapping of relative path -> text content)."""
    src_dir = archive_path.parent / f'__src_for_{archive_path.stem}__'
    src_dir.mkdir()
    try:
        for rel_path, content in files.items():
            file_path = src_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
        with py7zr.SevenZipFile(archive_path, 'w') as archive:
            for item in sorted(src_dir.iterdir()):
                archive.writeall(item, item.name)
    finally:
        shutil.rmtree(src_dir)


def read_7z_names(archive_path):
    with py7zr.SevenZipFile(archive_path, 'r') as archive:
        return set(archive.getnames())


# ---------------------------------------------------------------------------
# repack_merge
# ---------------------------------------------------------------------------

def test_repack_merge_when_tool_unpack_path_equals_update_folder_path(tmp_path):
    # Regression scenario: no single wrapping folder in the new download, so
    # tool_unpack_path IS update_folder_path. The old buggy code built the
    # old-version unpack path as a subdirectory of update_folder_path, which
    # meant it was nested inside tool_unpack_path and got wiped by
    # shutil.rmtree(tool_unpack_path) before the final move - raising
    # FileNotFoundError / losing the old version's files.
    updates_root = tmp_path / 'updates'
    updates_root.mkdir()
    update_folder_path = updates_root / 'ToolX'
    update_folder_path.mkdir()

    # new version's files land directly in update_folder_path (no wrapper)
    (update_folder_path / 'new_file.txt').write_text('new contents')

    tool_unpack_path = update_folder_path  # the regression condition

    tool_folder_path = tmp_path / 'tools' / 'ToolX'
    tool_folder_path.mkdir(parents=True)
    old_archive_path = tool_folder_path / 'ToolX - 1.0.0.7z'
    build_7z(old_archive_path, {'old_file.txt': 'old contents'})

    packer = make_packer(update_folder_path, tool_name='ToolX', tool_config={'local_version': '1.0.0'})

    # must complete without raising (old bug: FileNotFoundError)
    packer.repack_merge(tool_folder_path, tool_unpack_path)

    merged_names = {p.name for p in tool_unpack_path.iterdir()}
    assert 'new_file.txt' in merged_names
    assert 'old_file.txt' in merged_names
    assert (tool_unpack_path / 'new_file.txt').read_text() == 'new contents'
    assert (tool_unpack_path / 'old_file.txt').read_text() == 'old contents'

    # the isolated temp folder used for the old-version unpack must not have
    # been left behind (mkdtemp's dir= is update_folder_path.parent, i.e.
    # updates_root here)
    leftover_temp_dirs = [p for p in updates_root.iterdir() if p.name.startswith('ToolX_merge_')]
    assert leftover_temp_dirs == []


def test_repack_merge_returns_false_and_leaves_files_untouched_when_no_old_archive(tmp_path):
    updates_root = tmp_path / 'updates'
    updates_root.mkdir()
    update_folder_path = updates_root / 'ToolY'
    update_folder_path.mkdir()
    (update_folder_path / 'new_file.txt').write_text('new contents')

    tool_folder_path = tmp_path / 'tools' / 'ToolY'
    tool_folder_path.mkdir(parents=True)  # deliberately no old archive present

    packer = make_packer(update_folder_path, tool_name='ToolY', tool_config={'local_version': '1.0.0'})

    result = packer.repack_merge(tool_folder_path, update_folder_path)

    assert result is False
    assert (update_folder_path / 'new_file.txt').exists()


def test_repack_merge_isolated_temp_dir_not_nested_inside_tool_unpack_path(tmp_path, monkeypatch):
    # Directly assert the fix's mechanism: the temp dir used to unpack the old
    # version is created as a sibling of update_folder_path (dir=parent), never
    # underneath tool_unpack_path itself.
    updates_root = tmp_path / 'updates'
    updates_root.mkdir()
    update_folder_path = updates_root / 'ToolX'
    update_folder_path.mkdir()
    (update_folder_path / 'new_file.txt').write_text('new contents')
    tool_unpack_path = update_folder_path

    tool_folder_path = tmp_path / 'tools' / 'ToolX'
    tool_folder_path.mkdir(parents=True)
    old_archive_path = tool_folder_path / 'ToolX - 1.0.0.7z'
    build_7z(old_archive_path, {'old_file.txt': 'old contents'})

    packer = make_packer(update_folder_path, tool_name='ToolX', tool_config={'local_version': '1.0.0'})

    created_dirs = []
    original_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(*args, **kwargs):
        created = original_mkdtemp(*args, **kwargs)
        created_dirs.append(pathlib.Path(created))
        return created

    monkeypatch.setattr(tempfile, 'mkdtemp', spy_mkdtemp)

    packer.repack_merge(tool_folder_path, tool_unpack_path)

    assert len(created_dirs) == 1
    temp_dir = created_dirs[0]
    assert tool_unpack_path.resolve() not in temp_dir.resolve().parents
    assert temp_dir.resolve() != tool_unpack_path.resolve()


# ---------------------------------------------------------------------------
# repack_step
# ---------------------------------------------------------------------------

def test_repack_step_temp_archive_not_nested_in_tool_unpack_path(tmp_path, monkeypatch):
    # Regression: when tool_unpack_path == unpack_folder_path (no wrapping
    # folder), the temp folder holding the archive-under-construction must be
    # a sibling of unpack_folder_path, never a subdirectory of it - otherwise
    # the `for item in sorted(pathlib.Path(tool_unpack_path).iterdir())` loop
    # would try to include the very archive it's writing.
    updates_root = tmp_path / 'updates'
    updates_root.mkdir()
    unpack_folder_path = updates_root / 'ToolZ'
    unpack_folder_path.mkdir()
    (unpack_folder_path / 'file1.txt').write_text('data1')
    (unpack_folder_path / 'file2.txt').write_text('data2')

    tool_unpack_path = unpack_folder_path  # the regression condition

    tool_folder_path = tmp_path / 'tools' / 'ToolZ'
    tool_folder_path.mkdir(parents=True)

    packer = make_packer(unpack_folder_path, tool_name='ToolZ', tool_config={}, save_format_type='full')

    created_dirs = []
    original_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(*args, **kwargs):
        created = original_mkdtemp(*args, **kwargs)
        created_dirs.append(pathlib.Path(created))
        return created

    monkeypatch.setattr(tempfile, 'mkdtemp', spy_mkdtemp)

    result = packer.repack_step(tool_folder_path, tool_unpack_path, unpack_folder_path, version='2.0.0')

    assert len(created_dirs) == 1
    temp_dir = created_dirs[0]
    assert tool_unpack_path.resolve() not in temp_dir.resolve().parents
    assert temp_dir.resolve() != tool_unpack_path.resolve()

    # source files untouched (never wiped/consumed by the archive build)
    assert (unpack_folder_path / 'file1.txt').exists()
    assert (unpack_folder_path / 'file2.txt').exists()

    # temp dir cleaned up afterwards
    assert not temp_dir.exists()

    # the resulting archive landed in tool_folder_path and contains both files
    assert result['save_compress_name'] == 'ToolZ - 2.0.0.7z'
    archive_path = tool_folder_path / result['save_compress_name']
    assert archive_path.exists()
    assert read_7z_names(archive_path) == {'file1.txt', 'file2.txt'}


def test_repack_step_cleans_up_temp_dir_even_on_failure(tmp_path, monkeypatch):
    updates_root = tmp_path / 'updates'
    updates_root.mkdir()
    unpack_folder_path = updates_root / 'ToolFail'
    unpack_folder_path.mkdir()
    (unpack_folder_path / 'file1.txt').write_text('data1')

    tool_folder_path = tmp_path / 'tools' / 'ToolFail'
    tool_folder_path.mkdir(parents=True)

    packer = make_packer(unpack_folder_path, tool_name='ToolFail', tool_config={}, save_format_type='full')

    def boom(*args, **kwargs):
        raise RuntimeError('simulated archive failure')

    monkeypatch.setattr(py7zr, 'SevenZipFile', boom)

    with pytest.raises(RuntimeError):
        packer.repack_step(tool_folder_path, unpack_folder_path, unpack_folder_path, version='1.0.0')

    leftover_temp_dirs = [p for p in updates_root.iterdir() if p.name.startswith('ToolFail_repack_')]
    assert leftover_temp_dirs == []
