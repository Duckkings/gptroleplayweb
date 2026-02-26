# Core Module

## Purpose
- Provide infrastructure helpers: paths, JSON IO, save bundle storage, token usage, local dialogs.

Files:
- `storage.py`: config/save path state, atomic JSON write, and split save bundle read/write.
- `token_usage.py`: token usage aggregation by `session_id`.
- `dialogs.py`: directory picker dialog for desktop environments.

## Key APIs
- `storage_state.config_path`, `storage_state.save_path`
- `storage_state.set_config_path(raw_path)`
- `storage_state.set_save_path(raw_path)`
- `write_json_atomic(path, payload)`
- `read_json(path)`
- `write_save_payload(save_path, payload)`
- `read_save_payload(save_path)`
- `token_usage_store.add(session_id, source, input_tokens, output_tokens)`
- `token_usage_store.get(session_id)`

## Usage Example
```python
from app.core.storage import storage_state, write_save_payload
from app.core.token_usage import token_usage_store

write_save_payload(storage_state.save_path, payload)
token_usage_store.add("sess_xxx", "chat", 120, 340)
```

## Notes
- `storage_state` is global mutable state; do not reset paths per request.
- Save data is stored as a split bundle (`*.bundle`) and a lightweight pointer JSON.
- `token_usage_store` already has internal locking.
