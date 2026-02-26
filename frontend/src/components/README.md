# Components Module

## Purpose
- Render UI components and local view behavior.
- Receive callbacks from `App.tsx`; do not call backend directly.

## Components
- `MapPanel.tsx`: world map, zone tree, sub-zone click-to-move, circles and labels.
- `AreaPanel.tsx`: area debug panel (clock, sub-zones, interactions).
- `GameLogPanel.tsx`: game logs and AI fetch limit setting.
- `PlayerPanel.tsx`: editable player static data.
- `DebugPanel.tsx`: API summary and local debug actions.

## Usage Pattern
```tsx
<MapPanel
  open={mapOpen}
  zones={mapSnapshot.zones}
  areaSnapshot={areaSnapshot}
  render={mapRender}
  playerPosition={mapSnapshot.player_position}
  playerSpeedMph={playerStatic.move_speed_mph}
  search={mapSearch}
  onSearch={setMapSearch}
  onMoveSubZone={(id) => void onMoveSubZone(id)}
  onMove={(zoneId) => void onMoveToZone(zoneId)}
  onInitClock={() => void onInitAreaClock()}
  onClose={() => setMapOpen(false)}
  onForceRegenerate={() => void onForceRegenerateMap()}
/>
```

## Notes
- Keep business state in `App.tsx`.
- Prop changes must stay aligned with `docs/design/gamedesign/areadesign.md` behavior rules.

