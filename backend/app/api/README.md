# API Module

## Purpose
- Define HTTP routes and bind request/response schemas.
- Map service exceptions to HTTP status codes.
- Keep business logic in services, not in route handlers.

Main file: `backend/app/api/routes.py`

## Route Groups (`/api/v1`)
- Base: `/health`, `/config/validate`
- Chat: `/chat`, `/chat/stream`
- Storage/Saves: `/storage/*`, `/saves/*`
- Map: `/world-map/regions/generate`, `/world-map/render`, `/world-map/move`
- Area: `/world/clock/init`, `/world/area/current`, `/world/area/move-sub-zone`
- Interactions: `/world/area/interactions/discover`, `/world/area/interactions/execute`
- Logs/Usage: `/logs/*`, `/token-usage`
- Player: `/player/static`, `/player/runtime`

## How To Add A New API
1. Add request/response models in `backend/app/models/schemas.py`.
2. Add business function in `backend/app/services/*`.
3. Add route and error mapping in `routes.py`.
4. Add frontend type and API wrapper in `frontend/src/types/app.ts` and `frontend/src/services/api.ts`.

## Error Mapping
- Not found -> `404`
- Conflict or invalid state -> `409`
- Upstream AI failure -> `502`
- Missing key or rate limit -> `401` / `429`
