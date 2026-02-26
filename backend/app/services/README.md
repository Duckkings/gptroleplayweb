# Services Module

## Purpose
- Implement business logic outside HTTP handlers.
- Combine AI calls, validation, persistence, and log writes.

Files:
- `chat_service.py`: chat orchestration and tool-calling loop.
- `world_service.py`: map, area, clock, interaction, save logic.

## Main APIs
### chat_service
- `chat_once(payload: ChatRequest)`
- `_tools_schema()`
- `_handle_tool_call(payload, tool_call)`

### world_service
- Map: `generate_regions`, `render_map`, `move_to_zone`
- Area: `init_world_clock`, `get_area_current`, `move_to_sub_zone`
- Interaction: `discover_interactions`, `execute_interaction`
- Save/log helpers: `get_current_save`, `save_current`, `add_game_log`

## Usage Example
```python
from app.models.schemas import AreaMoveSubZoneRequest
from app.services.world_service import move_to_sub_zone

result = move_to_sub_zone(AreaMoveSubZoneRequest(session_id="sess_xxx", to_sub_zone_id="sub_zone_a_1"))
print(result.duration_min, result.movement_feedback)
```

## Notes
- Keep business rules here, not in `routes.py`.
- Service layer is the source of truth for clock advancement and fallback rules.
- Any save-structure change must remain backward compatible.
