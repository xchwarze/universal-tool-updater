# Per-download-session state for consumer_patch and producer_patch.
#
# pypdl's internal task ids are scoped to a single Pypdl() session (always 0
# for a single-URL download), NOT globally unique — this project runs many
# concurrent Pypdl() sessions (one per Downloader.download_file call, up to
# --parallel-workers at once), so state can't be a bare module-level set or
# fatal/retry flags leak between unrelated concurrent downloads.
#
# Each Pypdl() session creates its own fresh asyncio.Queue pair, and the
# patched Consumer.process_tasks(in_queue, out_queue) and
# Producer.enqueue_tasks(in_queue, out_queue) both see the SAME queue object
# for one session (consumer's out_queue param == producer's in_queue param).
# Storing the state directly on that shared queue ties its lifetime to the
# queue's via normal garbage collection — no registry or cleanup step needed.


def get_session_state(queue):
    state = getattr(queue, '_utu_patch_state', None)
    if state is None:
        state = {'fatal_task_ids': set(), 'force_single_segment_task_ids': set()}
        queue._utu_patch_state = state
    return state
