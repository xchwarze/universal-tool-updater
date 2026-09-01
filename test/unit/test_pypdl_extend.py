"""
Unit tests for pypdl_extend.fatal_state: per-session state isolation.

This module backs concurrent Pypdl() sessions running in parallel worker
threads (one per Downloader.download_file call); state for one session key
must never leak into or be affected by another.
"""

from pypdl_extend import fatal_state


def test_get_session_state_returns_independent_dicts_for_different_keys():
    state_a = fatal_state.get_session_state('session-a')
    state_b = fatal_state.get_session_state('session-b')

    assert state_a is not state_b
    assert state_a == {'fatal_task_ids': set(), 'force_single_segment_task_ids': set()}
    assert state_b == {'fatal_task_ids': set(), 'force_single_segment_task_ids': set()}


def test_mutating_one_session_state_does_not_affect_another():
    state_a = fatal_state.get_session_state('session-c')
    state_b = fatal_state.get_session_state('session-d')

    state_a['fatal_task_ids'].add(1)
    state_a['force_single_segment_task_ids'].add(2)

    assert state_b['fatal_task_ids'] == set()
    assert state_b['force_single_segment_task_ids'] == set()


def test_get_session_state_returns_same_object_for_same_key():
    first = fatal_state.get_session_state('session-e')
    first['fatal_task_ids'].add(99)

    second = fatal_state.get_session_state('session-e')

    assert second is first
    assert second['fatal_task_ids'] == {99}


def test_discard_session_state_removes_it():
    fatal_state.get_session_state('session-f')['fatal_task_ids'].add(1)

    fatal_state.discard_session_state('session-f')

    # a fresh call after discard must yield a brand-new, empty state object,
    # not the old mutated one
    fresh = fatal_state.get_session_state('session-f')
    assert fresh == {'fatal_task_ids': set(), 'force_single_segment_task_ids': set()}


def test_discard_session_state_is_safe_for_unknown_key():
    # discarding a key that was never created must not raise
    fatal_state.discard_session_state('never-existed')
