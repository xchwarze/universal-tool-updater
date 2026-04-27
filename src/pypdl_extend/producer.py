# Monkey-patch pypdl's Producer.enqueue_tasks to handle special task states
# flagged by the patched consumer (see fatal_state.py):
# - Fatal task IDs are immediately marked as failed (no retry).
# - Single-segment-fallback task IDs are reconfigured to multisegment=False
#   and given an extra retry attempt before being re-dispatched.

from pypdl.producer import Producer

from .fatal_state import fatal_task_ids, force_single_segment_task_ids

# Save reference to the original method so we can delegate non-special cases to it
_original_enqueue_tasks = Producer.enqueue_tasks


async def _patched_enqueue_tasks(self, in_queue, out_queue):
    # Wrap in_queue.get to intercept flagged task IDs before normal retry logic
    original_get = in_queue.get

    async def filtered_get():
        while True:
            batch = await original_get()
            if batch is None:
                return None

            remaining_ids = []
            for task_id in batch:
                if task_id in fatal_task_ids:
                    # Fatal — mark as failed without retrying
                    task = self._tasks[task_id]
                    self.add_failed(task.url, task.callback)
                    fatal_task_ids.discard(task_id)
                elif task_id in force_single_segment_task_ids:
                    # Reconfigure task to single-segment mode and grant one more attempt
                    task = self._tasks[task_id]
                    task.multisegment = False

                    # Bump tries so this task gets re-dispatched (it was decremented to 0
                    # during the failed multi-segment attempt)
                    task.tries = max(task.tries, 1)
                    force_single_segment_task_ids.discard(task_id)
                    remaining_ids.append(task_id)
                else:
                    # Normal task — let the original logic handle it
                    remaining_ids.append(task_id)

            if remaining_ids:
                return remaining_ids

    # All IDs in this batch were handled here; loop and get the next batch
    in_queue.get = filtered_get
    try:
        await _original_enqueue_tasks(self, in_queue, out_queue)
    finally:
        # Restore original get to avoid side effects if Pypdl is reused
        in_queue.get = original_get


def apply():
    """Apply the producer monkey-patch."""
    Producer.enqueue_tasks = _patched_enqueue_tasks