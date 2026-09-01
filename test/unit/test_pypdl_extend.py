"""
Unit tests for pypdl_extend.fatal_state: per-session state isolation.

This module backs concurrent Pypdl() sessions running in parallel worker
threads (one per Downloader.download_file call); state for one session's
queue object must never leak into or be affected by another's.
"""

import asyncio

from pypdl_extend import fatal_state


def test_get_session_state_returns_independent_dicts_for_different_objects():
    queue_a = asyncio.Queue()
    queue_b = asyncio.Queue()

    state_a = fatal_state.get_session_state(queue_a)
    state_b = fatal_state.get_session_state(queue_b)

    assert state_a is not state_b
    assert state_a == {'fatal_task_ids': set(), 'force_single_segment_task_ids': set()}
    assert state_b == {'fatal_task_ids': set(), 'force_single_segment_task_ids': set()}


def test_mutating_one_session_state_does_not_affect_another():
    queue_a = asyncio.Queue()
    queue_b = asyncio.Queue()

    state_a = fatal_state.get_session_state(queue_a)
    state_b = fatal_state.get_session_state(queue_b)

    state_a['fatal_task_ids'].add(1)
    state_a['force_single_segment_task_ids'].add(2)

    assert state_b['fatal_task_ids'] == set()
    assert state_b['force_single_segment_task_ids'] == set()


def test_get_session_state_returns_same_object_for_same_queue():
    queue = asyncio.Queue()

    first = fatal_state.get_session_state(queue)
    first['fatal_task_ids'].add(99)

    second = fatal_state.get_session_state(queue)

    assert second is first
    assert second['fatal_task_ids'] == {99}
