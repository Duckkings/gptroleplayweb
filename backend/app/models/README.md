# Models Module

## Purpose
- Define canonical data contracts with Pydantic.
- Serve as the single source of truth for API, service, and save schemas.

Main file: `backend/app/models/schemas.py`

## Model Groups
- Chat: `ChatConfig`, `ChatRequest`, `ChatResponse`, `ToolEvent`
- Map: `Zone`, `MapSnapshot`, `RenderMapResponse`, `MoveResponse`
- Area: `AreaZone`, `AreaSubZone`, `AreaSnapshot`, `AreaMoveResult`
- Interactions: `AreaInteraction`, `AreaNpc`, `AreaDiscoverInteractionsResponse`
- Save/Logs: `SaveFile`, `GameLogEntry`, `GameLogSettings`
- Player: `PlayerStaticData`, `PlayerRuntimeData`

## Usage Example
```python
from app.models.schemas import AreaMoveSubZoneRequest

req = AreaMoveSubZoneRequest(session_id="sess_xxx", to_sub_zone_id="sub_zone_a_1")
```

## Change Rule
When a backend schema changes, update these in the same task:
1. `frontend/src/types/app.ts`
2. `frontend/src/services/api.ts` return/request typing
3. `docs/technical/technical.md` or a feature technical doc

