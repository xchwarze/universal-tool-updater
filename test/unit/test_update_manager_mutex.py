"""
Unit tests for UpdateManager.check_single_instance's mutex-file parsing.

This logic lives inline in check_single_instance (not a standalone
function), so rather than reimplementing/duplicating the parsing rule in the
test, these tests construct a real (but isolated) UpdateManager instance and
call the real method directly:

- monkeypatch.chdir() into a scratch tmp_path before constructing
  UpdateManager(), since __init__ reads 'tools.ini' and check_single_instance
  reads/writes 'mutex.lock' both relative to the current working directory.
  A missing tools.ini is harmless (configparser.read() no-ops on a missing
  file), and this guarantees the real repo's tools.ini/mutex.lock are never
  touched.
- self.arguments is normally an argparse.Namespace built by parse_arguments()
  from real CLI args; we don't want to parse actual CLI args in a unit test,
  so a minimal types.SimpleNamespace with just the one attribute
  check_single_instance reads (disable_mutex_check) is substituted directly.
- psutil.pid_exists and sys.exit are monkeypatched where a test needs to
  control/observe them, so nothing here depends on real OS process state or
  actually terminates the test process.
"""

import os
import sys
import types

import psutil
import pytest

from UpdateManager import UpdateManager


def make_manager(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = UpdateManager()
    manager.arguments = types.SimpleNamespace(disable_mutex_check=False)
    return manager


def test_garbage_mutex_content_is_treated_as_no_existing_pid(tmp_path, monkeypatch):
    manager = make_manager(tmp_path, monkeypatch)
    mutex_path = tmp_path / manager.process_mutex
    mutex_path.write_text('not-a-pid-garbage-!@#$')

    # a garbage (non-int) pid must short-circuit to existing_pid = None and
    # never reach the "is it alive" / "exit" branch at all
    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: pytest.fail('pid_exists should not be called'))
    monkeypatch.setattr(sys, 'exit', lambda code=0: pytest.fail(f'sys.exit({code!r}) should not be called'))

    # must not raise ValueError (the historical bug) or exit
    manager.check_single_instance()

    # the mutex file must have been regenerated with the current pid
    assert mutex_path.read_text().strip() == str(os.getpid())


def test_empty_mutex_content_is_treated_as_no_existing_pid(tmp_path, monkeypatch):
    manager = make_manager(tmp_path, monkeypatch)
    mutex_path = tmp_path / manager.process_mutex
    mutex_path.write_text('')

    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: pytest.fail('pid_exists should not be called'))
    monkeypatch.setattr(sys, 'exit', lambda code=0: pytest.fail(f'sys.exit({code!r}) should not be called'))

    manager.check_single_instance()

    assert mutex_path.read_text().strip() == str(os.getpid())


def test_valid_pid_of_dead_process_is_treated_as_stale(tmp_path, monkeypatch):
    manager = make_manager(tmp_path, monkeypatch)
    mutex_path = tmp_path / manager.process_mutex
    mutex_path.write_text('999999')  # syntactically valid, but not a live pid

    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: False)

    manager.check_single_instance()

    assert mutex_path.read_text().strip() == str(os.getpid())


def test_valid_pid_of_live_process_exits_without_overwriting_mutex(tmp_path, monkeypatch):
    manager = make_manager(tmp_path, monkeypatch)
    mutex_path = tmp_path / manager.process_mutex
    mutex_path.write_text('4321')

    monkeypatch.setattr(psutil, 'pid_exists', lambda pid: True)

    with pytest.raises(SystemExit):
        manager.check_single_instance()

    # must not have regenerated the mutex - it still belongs to the "other" process
    assert mutex_path.read_text().strip() == '4321'


def test_disable_mutex_check_skips_everything(tmp_path, monkeypatch):
    manager = make_manager(tmp_path, monkeypatch)
    manager.arguments.disable_mutex_check = True

    manager.check_single_instance()

    mutex_path = tmp_path / manager.process_mutex
    assert not mutex_path.exists()
