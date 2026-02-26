# Frontend Services Module

## Purpose
- Centralize all backend API calls for the frontend.
- Provide consistent JSON parsing, error handling, and debug reporting.

Main file: `frontend/src/services/api.ts`

## API Groups
- Chat: `sendChat`, `streamChat`
- Config/Paths: `validateConfig`, `saveConfig`, `getConfigPath`, `pickSavePath`
- Save: `getCurrentSave`, `importSave`, `clearSave`
- Map: `generateRegions`, `renderWorldMap`, `moveToZone`
- Area: `initWorldClock`, `getCurrentArea`, `moveToSubZone`
- Interaction: `discoverAreaInteractions`, `executeAreaInteraction`
- Logs/Usage: `getGameLogs`, `setGameLogSettings`, `getTokenUsage`

## Usage Example
```ts
import { getCurrentArea, moveToSubZone } from '../services/api';

const area = await getCurrentArea(sessionId, report);
const moved = await moveToSubZone({ session_id: sessionId, to_sub_zone_id: subZoneId, config }, report);
```

## Notes
- Add new endpoint wrappers here before using them in components.
- Keep `requestJson` as the only place for common error formatting.
