# Per-download-session state for consumer_patch and producer_patch.
#
# pypdl's internal task ids are scoped to a single Pypdl() session (always 0
# for a single-URL download), NOT globally unique — this project runs many
# concurrent Pypdl() sessions (one per Downloader.download_file call, up to
# --parallel-workers at once), so state can't be a bare module-level set or
# fatal/retry flags leak between unrelated concurrent downloads.
#
# Each Pypdl() session creates its own fresh asyncio.Queue pair; the patched
# Consumer.process_tasks(in_queue, out_queue) and Producer.enqueue_tasks(in_queue, out_queue)
# both see the SAME producer-queue object for one session (consumer's out_queue
# param == producer's in_queue param), so id() of that queue is a reliable
# per-session key with no cross-session collisions.

import threading

_lock = threading.Lock()
_sessions = {}


def get_session_state(session_key):
    with _lock:
        state = _sessions.get(session_key)
        if state is None:
            state = {'fatal_task_ids': set(), 'force_single_segment_task_ids': set()}
            _sessions[session_key] = state
        return state


def discard_session_state(session_key):
    with _lock:
        _sessions.pop(session_key, None)
