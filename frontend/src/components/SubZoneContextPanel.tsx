import { useEffect, useMemo, useRef, useState } from 'react';
import type { AreaSubZone, PublicTurnPresentation, SubZoneChatTurn } from '../types/app';
import { PublicTurnNarrativePane } from './PublicTurnNarrativePane';
import { PublicTurnSettlementPane } from './PublicTurnSettlementPane';
import { SceneEventCard } from './SceneEventCard';

type Props = {
  subZone: AreaSubZone | null;
};

const HIDDEN_EVENT_KINDS = new Set(['encounter_progress', 'encounter_resolution']);

function legacyPresentation(turn: SubZoneChatTurn): PublicTurnPresentation | null {
  if (turn.public_turn_presentation) {
    return turn.public_turn_presentation;
  }
  if (!turn.gm_narration.trim() && turn.events.length === 0) {
    return null;
  }
  return {
    round_id: turn.public_round_id ?? turn.turn_id,
    round_number: turn.public_round_number ?? 0,
    phase: turn.public_phase ?? 'idle',
    initiative_order: [],
    settlement_entries: [],
    narrative_entries: [],
    accumulated_narration: turn.gm_narration ?? '',
    narrative_status: turn.gm_narration.trim() ? 'complete' : 'empty',
    round_narration: turn.gm_narration ?? '',
    round_narration_status: turn.gm_narration.trim() ? 'ready' : 'pending',
  };
}

export function SubZoneContextPanel({ subZone }: Props) {
  const turns = subZone?.chat_context?.recent_turns ?? [];
  const publicTurnState = subZone?.chat_context?.public_turn_state;
  const currentRound = publicTurnState?.current_round ?? null;
  const subZoneId = subZone?.sub_zone_id ?? null;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);
  const lastSubZoneIdRef = useRef<string | null>(null);
  const [collapsed, setCollapsed] = useState(true);

  useEffect(() => {
    if (!subZoneId) return;
    if (lastSubZoneIdRef.current === subZoneId) return;
    lastSubZoneIdRef.current = subZoneId;
    stickToBottomRef.current = true;
    setCollapsed(true);
    window.requestAnimationFrame(() => {
      const node = containerRef.current;
      if (!node) return;
      node.scrollTop = node.scrollHeight;
    });
  }, [subZoneId]);

  useEffect(() => {
    if (!subZoneId || turns.length === 0 || !stickToBottomRef.current || collapsed) return;
    window.requestAnimationFrame(() => {
      const node = containerRef.current;
      if (!node) return;
      node.scrollTop = node.scrollHeight;
    });
  }, [collapsed, subZoneId, turns.length]);

  const renderedTurns = useMemo(
    () =>
      turns.map((turn) => ({
        turn,
        presentation: legacyPresentation(turn),
        visibleEvents: turn.events.filter((event) => !HIDDEN_EVENT_KINDS.has(event.event_kind)),
      })),
    [turns],
  );

  if (!subZone || turns.length === 0) return null;

  const onScroll = () => {
    const node = containerRef.current;
    if (!node) return;
    const distanceToBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
    stickToBottomRef.current = distanceToBottom <= 80;
  };

  return (
    <section className="subzone-context-panel">
      <header className="subzone-context-header">
        <div>
          <h3>地区上下文</h3>
          <p>{subZone.name} 的历史公开回合会保存在这里，默认折叠。</p>
          {publicTurnState && (
            <p className="hint">
              Public Turn: {currentRound ? `round ${currentRound.round_number} / ${currentRound.phase}` : 'idle'} / risk{' '}
              {currentRound?.environment_risk_level ?? publicTurnState.environment_risk_level}
            </p>
          )}
        </div>
        <button type="button" onClick={() => setCollapsed((prev) => !prev)}>
          {collapsed ? `展开历史（${turns.length}）` : '收起历史'}
        </button>
      </header>
      {!collapsed && (
        <div ref={containerRef} className="subzone-context-list" onScroll={onScroll}>
          {renderedTurns.map(({ turn, presentation, visibleEvents }) => (
            <article key={turn.turn_id} className="subzone-context-turn">
              <div className="subzone-context-turn-header">
                <strong>{turn.world_time_text}</strong>
                <div className="subzone-context-meta">
                  <span>{turn.player_mode === 'passive' ? '自动推进' : '主动回合'}</span>
                  {typeof turn.public_round_number === 'number' && <span>Public Round: {turn.public_round_number}</span>}
                  {turn.public_phase && <span>Phase: {turn.public_phase}</span>}
                </div>
              </div>
              {presentation ? (
                <div className="public-turn-output-layout compact">
                  <PublicTurnSettlementPane presentation={presentation} />
                  <PublicTurnNarrativePane presentation={presentation} variant="history" sceneEvents={[]} />
                </div>
              ) : null}
              {visibleEvents.length > 0 && (
                <div className="subzone-context-events">
                  {visibleEvents.map((event, index) => (
                    <SceneEventCard
                      key={`${turn.turn_id}_${event.actor_id || event.actor_name}_${index}`}
                      event={{
                        event_kind: event.event_kind,
                        actor_name: event.actor_name,
                        content: event.content,
                        metadata: event.metadata,
                      }}
                      compact
                    />
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
