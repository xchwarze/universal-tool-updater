# Shared state between consumer_patch and producer_patch.
# - fatal_task_ids: task IDs that should be marked as failed without retry.
# - force_single_segment_task_ids: task IDs that should be retried with multisegment=False.

fatal_task_ids = set()
force_single_segment_task_ids = set()