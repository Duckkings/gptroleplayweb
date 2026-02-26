import { useEffect, useMemo, useRef, useState } from 'react';
import type { AreaSnapshot, Position, RenderResult, Zone } from '../types/app';

type Props = {
  open: boolean;
  zones: Zone[];
  areaSnapshot: AreaSnapshot | null;
  render: RenderResult | null;
  playerPosition: Position | null;
  playerSpeedMph: number;
  search: string;
  onSearch: (next: string) => void;
  onClose: () => void;
  onForceRegenerate: () => void;
  onMove: (zoneId: string) => void;
  onMoveSubZone: (subZoneId: string) => void;
  onInitClock: () => void;
};

type ZoneDetail = {
  zone: Zone;
  distanceM: number;
  durationMin: number;
};

type Point = { x: number; y: number };
const MAX_ZOOMED_IN_HALF_RANGE_M = 50;
const ZOOM_STEP_PERCENT = 2;

function calcTravel(player: Position | null, zone: Zone, speed: number): { distanceM: number; durationMin: number } {
  if (!player) return { distanceM: 0, durationMin: 0 };
  const dx = zone.x - player.x;
  const dy = zone.y - player.y;
  const distanceM = Math.sqrt(dx * dx + dy * dy);
  const safeSpeed = Math.max(1, speed);
  const durationMin = Math.max(1, Math.ceil((distanceM / safeSpeed) * 60));
  return { distanceM, durationMin };
}

function calcSubZoneTravelMin(
  fromCoord: { x: number; y: number; z: number } | null,
  to: AreaSnapshot['sub_zones'][number],
  speed: number,
): number {
  if (!fromCoord) return 0;
  const dx = to.coord.x - fromCoord.x;
  const dy = to.coord.y - fromCoord.y;
  const dz = to.coord.z - fromCoord.z;
  const distanceM = Math.sqrt(dx * dx + dy * dy + dz * dz);
  const safeSpeed = Math.max(1, speed);
  return Math.max(0, Math.ceil((distanceM / safeSpeed) * 60));
}

export function MapPanel({
  open,
  zones,
  areaSnapshot,
  render,
  playerPosition,
  playerSpeedMph,
  search,
  onSearch,
  onClose,
  onForceRegenerate,
  onMove,
  onMoveSubZone,
  onInitClock,
}: Props) {
  const [detail, setDetail] = useState<ZoneDetail | null>(null);
  const [expandedZoneIds, setExpandedZoneIds] = useState<Record<string, boolean>>({});
  const [lastSelectedZoneId, setLastSelectedZoneId] = useState<string | null>(null);
  const prevCurrentZoneIdRef = useRef<string>('');
  const [zoomPercent, setZoomPercent] = useState(100);
  const [pan, setPan] = useState<Point>({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const [dragStart, setDragStart] = useState<Point>({ x: 0, y: 0 });
  const [boardSize, setBoardSize] = useState({ w: 760, h: 520 });
  const boardRef = useRef<HTMLDivElement | null>(null);
  const viewInitializedRef = useRef(false);

  const filtered = useMemo(() => zones.filter((z) => z.name.includes(search) || z.zone_id.includes(search)), [zones, search]);
  const areaZones = areaSnapshot?.zones ?? [];
  const areaSubZones = areaSnapshot?.sub_zones ?? [];
  const currentZoneId = areaSnapshot?.current_zone_id ?? playerPosition?.zone_id ?? '';
  const currentSubZoneId = areaSnapshot?.current_sub_zone_id ?? '';
  const currentSubZone = useMemo(
    () => areaSubZones.find((s) => s.sub_zone_id === currentSubZoneId) ?? null,
    [areaSubZones, currentSubZoneId],
  );
  const currentZone = useMemo(() => areaZones.find((z) => z.zone_id === currentZoneId) ?? null, [areaZones, currentZoneId]);

  const minX = useMemo(() => {
    const xs = [...((render?.nodes ?? []).map((n) => n.x)), ...((render?.sub_nodes ?? []).map((n) => n.x))];
    return xs.length ? Math.min(...xs) : 0;
  }, [render?.nodes, render?.sub_nodes]);
  const maxX = useMemo(() => {
    const xs = [...((render?.nodes ?? []).map((n) => n.x)), ...((render?.sub_nodes ?? []).map((n) => n.x))];
    return xs.length ? Math.max(...xs) : 1;
  }, [render?.nodes, render?.sub_nodes]);
  const minY = useMemo(() => {
    const ys = [...((render?.nodes ?? []).map((n) => n.y)), ...((render?.sub_nodes ?? []).map((n) => n.y))];
    return ys.length ? Math.min(...ys) : 0;
  }, [render?.nodes, render?.sub_nodes]);
  const maxY = useMemo(() => {
    const ys = [...((render?.nodes ?? []).map((n) => n.y)), ...((render?.sub_nodes ?? []).map((n) => n.y))];
    return ys.length ? Math.max(...ys) : 1;
  }, [render?.nodes, render?.sub_nodes]);

  const spanX = Math.max(1, maxX - minX);
  const spanY = Math.max(1, maxY - minY);
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;

  const effectivePlayer = useMemo(() => {
    if (playerPosition) return { x: playerPosition.x, y: playerPosition.y, zone_id: playerPosition.zone_id };
    if (render?.player_marker) return { x: render.player_marker.x, y: render.player_marker.y, zone_id: '' };
    return null;
  }, [playerPosition, render?.player_marker]);

  const fitScale = useMemo(() => {
    const innerW = Math.max(100, boardSize.w - 60);
    const innerH = Math.max(100, boardSize.h - 60);
    return Math.max(0.01, Math.min(innerW / spanX, innerH / spanY));
  }, [boardSize.h, boardSize.w, spanX, spanY]);

  const maxZoomInScale = useMemo(() => {
    const innerW = Math.max(100, boardSize.w - 60);
    const innerH = Math.max(100, boardSize.h - 60);
    const maxSpan = MAX_ZOOMED_IN_HALF_RANGE_M * 2;
    return Math.max(0.01, Math.min(innerW / maxSpan, innerH / maxSpan));
  }, [boardSize.h, boardSize.w]);

  const currentScale = useMemo(() => {
    const p = Math.min(100, Math.max(0, zoomPercent));
    const t = (100 - p) / 100;
    const low = fitScale;
    const high = Math.max(fitScale, maxZoomInScale);
    return low + (high - low) * t;
  }, [fitScale, maxZoomInScale, zoomPercent]);

  const toScreen = (x: number, y: number) => {
    const s = currentScale;
    return {
      left: (x - centerX) * s + boardSize.w / 2 + pan.x,
      top: (centerY - y) * s + boardSize.h / 2 + pan.y,
    };
  };

  const centerOnPoint = (x: number, y: number) => {
    const s = currentScale;
    const px = (x - centerX) * s;
    const py = (centerY - y) * s;
    setPan({ x: -px, y: -py });
  };

  const centerOnPlayer = () => {
    if (!effectivePlayer) return;
    centerOnPoint(effectivePlayer.x, effectivePlayer.y);
  };

  useEffect(() => {
    if (!open) return;
    if (viewInitializedRef.current) return;
    const id = window.requestAnimationFrame(() => {
      centerOnPlayer();
      viewInitializedRef.current = true;
    });
    return () => window.cancelAnimationFrame(id);
  }, [open, effectivePlayer?.x, effectivePlayer?.y, fitScale]);

  useEffect(() => {
    if (!open) return;
    if ((render?.nodes?.length ?? 0) === 0) {
      viewInitializedRef.current = false;
    }
  }, [open, render?.nodes?.length]);

  useEffect(() => {
    if (!currentZoneId) return;
    if (prevCurrentZoneIdRef.current !== currentZoneId) {
      setExpandedZoneIds({ [currentZoneId]: true });
      prevCurrentZoneIdRef.current = currentZoneId;
      return;
    }
    setExpandedZoneIds((prev) => ({ ...prev, [currentZoneId]: true }));
  }, [currentZoneId]);

  useEffect(() => {
    if (!open) return;
    const el = boardRef.current;
    if (!el) return;
    const resize = () => {
      const w = Math.max(100, el.clientWidth);
      const h = Math.max(100, el.clientHeight);
      setBoardSize({ w, h });
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    return () => observer.disconnect();
  }, [open]);

  if (!open) return null;

  const openDetail = (zoneId: string) => {
    const zone = zones.find((z) => z.zone_id === zoneId);
    if (!zone) return;
    const travel = calcTravel(playerPosition, zone, playerSpeedMph);
    setDetail({ zone, ...travel });
  };

  const focusZoneFromList = (zoneId: string) => {
    const zone = zones.find((z) => z.zone_id === zoneId);
    if (!zone) return;
    centerOnPoint(zone.x, zone.y);
    openDetail(zoneId);
  };

  const onZoneListClick = (zoneId: string) => {
    if (lastSelectedZoneId === zoneId) {
      setExpandedZoneIds((prev) => ({ ...prev, [zoneId]: !prev[zoneId] }));
    } else {
      setLastSelectedZoneId(zoneId);
      focusZoneFromList(zoneId);
    }
  };

  return (
    <section className="map-panel card">
      <header className="chat-header">
        <div>
          <h2>世界地图</h2>
          <p>当前区块: {currentZoneId || playerPosition?.zone_id || '未知'}</p>
          <p>当前子区块: {currentSubZone?.name ?? '未知'}</p>
        </div>
        <div className="actions">
          <button onClick={onInitClock}>初始化时钟</button>
          <button onClick={onForceRegenerate}>强制重新生成</button>
          <button onClick={centerOnPlayer}>定位玩家</button>
          <button onClick={onClose}>关闭地图</button>
        </div>
      </header>

      <div className="map-layout">
        <aside className="map-zones">
          <input value={search} onChange={(e) => onSearch(e.target.value)} placeholder="搜索区块" />
          <div className="zone-name-list">
            {(areaZones.length > 0 ? areaZones : filtered)
              .filter((z) => z.name.includes(search) || z.zone_id.includes(search))
              .map((z) => {
                const subZones = areaSubZones.filter((s) => s.zone_id === z.zone_id);
                const expanded = !!expandedZoneIds[z.zone_id];
                return (
                  <div key={z.zone_id} className={`zone-tree-item ${currentZoneId === z.zone_id ? 'current' : ''}`}>
                    <button className="zone-name-item" onClick={() => onZoneListClick(z.zone_id)}>
                      {z.name}
                      {currentZoneId === z.zone_id ? '（当前）' : ''}
                    </button>
                    <p className="zone-meta">
                      类型: {z.zone_type} | 规模: {z.size} | 范围: {z.radius_m}m
                    </p>
                    {expanded && (
                      <div className="subzone-list">
                        {subZones.map((sub) => (
                          <div key={sub.sub_zone_id} className={`subzone-item ${currentSubZoneId === sub.sub_zone_id ? 'current' : ''}`}>
                            <button onClick={() => onMoveSubZone(sub.sub_zone_id)}>
                              {sub.name}
                              {currentSubZoneId === sub.sub_zone_id ? '（当前）' : ''}
                              {` | 预计${calcSubZoneTravelMin(
                                currentSubZone
                                  ? { x: currentSubZone.coord.x, y: currentSubZone.coord.y, z: currentSubZone.coord.z }
                                  : currentZone
                                    ? { x: currentZone.center.x, y: currentZone.center.y, z: currentZone.center.z }
                                    : playerPosition
                                      ? { x: playerPosition.x, y: playerPosition.y, z: playerPosition.z }
                                      : null,
                                sub,
                                playerSpeedMph,
                              )}分钟`}
                            </button>
                          </div>
                        ))}
                        {subZones.length === 0 && <p className="hint">暂无子区块</p>}
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        </aside>

        <section className="map-board">
          <p>
            视野: x[{minX}, {maxX}] y[{minY}, {maxY}]
          </p>
          <div className="actions map-tools">
            <label className="zoom-label">
              缩放: {zoomPercent}% (100%=整图)
              <input type="range" min={0} max={100} step={1} value={zoomPercent} onChange={(e) => setZoomPercent(Number(e.target.value))} />
            </label>
          </div>

          <div
            ref={boardRef}
            className="coord-board"
            onMouseDown={(e) => {
              if (e.button !== 1) return;
              e.preventDefault();
              setDragging(true);
              setDragStart({ x: e.clientX, y: e.clientY });
            }}
            onMouseMove={(e) => {
              if (!dragging) return;
              const dx = e.clientX - dragStart.x;
              const dy = e.clientY - dragStart.y;
              setPan((p) => ({ x: p.x + dx, y: p.y + dy }));
              setDragStart({ x: e.clientX, y: e.clientY });
            }}
            onMouseUp={() => setDragging(false)}
            onMouseLeave={() => setDragging(false)}
            onWheel={(e) => {
              e.preventDefault();
              const direction = e.deltaY < 0 ? -1 : 1;
              const next = Math.min(100, Math.max(0, zoomPercent + direction * ZOOM_STEP_PERCENT));
              setZoomPercent(next);
            }}
            onContextMenu={(e) => e.preventDefault()}
          >
            <svg className="coord-links" width={boardSize.w} height={boardSize.h} viewBox={`0 0 ${boardSize.w} ${boardSize.h}`}>
              {(render?.circles ?? []).map((c) => {
                const center = toScreen(c.center_x, c.center_y);
                const rpx = c.radius_m * currentScale;
                const zoneName = (render?.nodes ?? []).find((n) => n.zone_id === c.zone_id)?.name ?? c.zone_id;
                return (
                  <g key={`circle_${c.zone_id}`}>
                    <circle cx={center.left} cy={center.top} r={Math.max(2, rpx)} className="zone-circle" />
                    <text x={center.left} y={center.top} className="zone-circle-label">
                      {zoneName}
                    </text>
                  </g>
                );
              })}
              {(render?.nodes ?? []).map((node) => {
                if (!effectivePlayer) return null;
                if (effectivePlayer.zone_id && node.zone_id === effectivePlayer.zone_id) return null;
                const from = toScreen(node.x, node.y);
                const to = toScreen(effectivePlayer.x, effectivePlayer.y);
                return <line key={`line_${node.zone_id}`} x1={from.left} y1={from.top} x2={to.left} y2={to.top} />;
              })}
            </svg>

            {(render?.nodes ?? []).map((node) => {
              const pos = toScreen(node.x, node.y);
              const isPlayer = effectivePlayer?.zone_id ? effectivePlayer.zone_id === node.zone_id : false;
              return (
                <button
                  key={node.zone_id}
                  className={`coord-node ${isPlayer ? 'active' : ''}`}
                  style={{ left: `${pos.left}px`, top: `${pos.top}px` }}
                  title={`${node.name} (${node.x},${node.y})`}
                  onClick={() => openDetail(node.zone_id)}
                >
                  <span className="dot" />
                  <span className="coord-node-label always">{node.name}</span>
                </button>
              );
            })}

            {(render?.sub_nodes ?? []).map((node) => {
              const pos = toScreen(node.x, node.y);
              return (
                <button
                  key={node.sub_zone_id}
                  className="subzone-node"
                  style={{ left: `${pos.left}px`, top: `${pos.top}px` }}
                  title={node.name}
                  onClick={() => onMoveSubZone(node.sub_zone_id)}
                >
                  <span className="subzone-dot-mark" />
                  <span className="subzone-dot-label">{node.name}</span>
                </button>
              );
            })}

            {effectivePlayer && (() => {
              const pos = toScreen(effectivePlayer.x, effectivePlayer.y);
              return (
                <div className="player-marker" style={{ left: `${pos.left}px`, top: `${pos.top}px` }} title="玩家当前位置">
                  P
                </div>
              );
            })()}
          </div>
        </section>
      </div>

      {detail && (
        <div className="modal-mask">
          <div className="modal-card">
            <h3>{detail.zone.name}</h3>
            <p>区块ID: {detail.zone.zone_id}</p>
            <p>
              类型: {detail.zone.zone_type} | 规模: {detail.zone.size} | 范围: {detail.zone.radius_m}m
            </p>
            <p>
              坐标: ({detail.zone.x}, {detail.zone.y}, {detail.zone.z})
            </p>
            <p>{detail.zone.description}</p>
            <p>直线距离: {detail.distanceM.toFixed(2)} m</p>
            <p>预计耗时: {detail.durationMin} 分钟</p>
            <div className="actions">
              <button
                onClick={() => {
                  onMove(detail.zone.zone_id);
                  setDetail(null);
                }}
              >
                确定移动
              </button>
              <button onClick={() => setDetail(null)}>返回</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
