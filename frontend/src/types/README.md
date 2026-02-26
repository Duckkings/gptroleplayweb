# Frontend Types Module

## Purpose
- Hold frontend domain type definitions.
- Mirror backend schema fields from `backend/app/models/schemas.py`.

Main file: `frontend/src/types/app.ts`

## Type Groups
- Base: `AppConfig`, `ChatMessage`, `Usage`
- Map: `Zone`, `MapSnapshot`, `RenderResult`
- Area: `AreaZone`, `AreaSubZone`, `AreaSnapshot`, `AreaMoveResult`
- Player: `PlayerStaticData`, `PlayerRuntimeData`
- Save/Logs: `SaveFile`, `GameLogEntry`, `GameLogSettings`

## Usage Example
```ts
import type { AreaSnapshot, AreaMoveResult } from '../types/app';
```

## Notes
- Update this file first when backend schema changes.
- Avoid using `any` for core domain objects.
