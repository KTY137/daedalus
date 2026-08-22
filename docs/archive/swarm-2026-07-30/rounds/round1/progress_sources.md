# Claims about `progress_sources.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] record_offload_result: if result['rolled_back'] is true but 'dirty_unreverted' key missing, applied becomes False (instead of True) even if files left dirty.
2. [risk] snapshot_from_ledger: numeric string confusion – call with effect_key='123' queries by id=123 first, may return wrong intent or None.
3. [risk] track_call: heartbeat thread writes to progress log concurrently without explicit thread-safety guarantee for P.heartbeat.
4. [risk] Audit limited – snapshot_from_bridge and snapshot_any not visible in provided slice; potential issues there unknown.
5. [risk] watch_stream: exception swallowing hides all progress recording failures; no recovery or fallback logging.
6. [todo] Fix snapshot_from_ledger: disambiguate effect key vs id (e.g., try effect string first, then fallback to int id if input is numeric and not matched).
7. [todo] Audit offload.py to ensure dirty_unreverted always present when rolled_back; or handle missing key as error.
8. [todo] Verify P.heartbeat thread safety; if not, document and perhaps protect with lock in heartbeat thread.
9. [todo] Consider logging exceptions in watch_stream to stderr or dedicated error log for diagnostics.