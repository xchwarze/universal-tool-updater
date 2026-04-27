# Monkey-patch pypdl's Consumer.process_tasks to handle problematic errors.
# By default, pypdl re-queues ALL exceptions regardless of whether retrying makes sense.
# This patch:
# - Marks fatal task IDs (404, 403, etc.) so the producer fails them immediately.
# - Marks segment-size-mismatch task IDs so the producer retries them as single-segment.

import asyncio
from aiohttp import ClientResponseError
from pypdl.consumer import Consumer

from .fatal_state import fatal_task_ids, force_single_segment_task_ids

# Errors that should trigger a single-segment retry (server doesn't honor byte ranges)
_SINGLE_SEGMENT_FALLBACK_ERRORS = (
    "Incorrect segment size",
)

# HTTP status codes that are permanent failures — no point retrying these
# Note: 5xx codes are intentionally excluded since they are transient server errors
_FATAL_STATUS_CODES = (400, 401, 403, 404, 410)


async def _patched_process_tasks(self, in_queue, out_queue):
    while True:
        task = await in_queue.get()
        if task is None:
            break
        
        try:
            await self._download(task)
        except asyncio.CancelledError:
            raise
        except ClientResponseError as http_error:
            if http_error.status in _FATAL_STATUS_CODES:
                # Fatal HTTP error — mark task ID as fatal so producer won't retry it
                self._logger.warning("Fatal HTTP %s for %s, skipping retries", http_error.status, task[0])
                fatal_task_ids.add(task[0])
            else:
                # Transient HTTP error (e.g. 503, 429) — allow retry
                self._logger.warning("Transient HTTP %s, will retry", http_error.status)

            # Always re-queue so the producer can track task completion (failed or retry)
            await out_queue.put([task[0]])
        except Exception as download_error:
            if any(msg in str(download_error) for msg in _SINGLE_SEGMENT_FALLBACK_ERRORS):
                # Server doesn't respect byte ranges — retry the task as single-segment
                self._logger.warning("Segment error, retrying as single-segment: %s", download_error)
                force_single_segment_task_ids.add(task[0])
            else:
                # Unknown error — allow retry as original behavior
                self._logger.warning("Unknown error, will retry: %s", download_error)

            # Always re-queue so the producer can track task completion (failed or retry)
            await out_queue.put([task[0]])
        finally:
            # Always clean up worker state regardless of outcome
            self._workers.clear()
            self._show_size = True


def apply():
    """Apply the consumer monkey-patch."""
    Consumer.process_tasks = _patched_process_tasks