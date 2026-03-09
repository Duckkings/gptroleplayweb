import { useEffect, useRef } from 'react';
import type { AreaSubZone, SubZoneChatTurnEvent } from '../types/app';

type Props = {
  subZone: AreaSubZone | null;
};

const HIDDEN_EVENT_KINDS = new Set<SubZoneChatTurnEvent['event_kind']>(['encounter_progress', 'encounter_resolution']);

const EVENT_LABEL: Record<SubZoneChatTurnEvent['event_kind'], string> = {
  encounter_progress: '遭遇推进',
  encounter_resolution: '遭遇结算',
  npc_reply: 'NPC',
  team_reply: '队友',
  system_notice: '系统',
  public_actor_resolution: '公开轮次',
  role_desire_surface: '角色欲望',
  companion_story_surface: '队友故事',
  reputation_update: '区域声望',
  encounter_situation_update: '局势值',
};

export function SubZoneContextPanel({ subZone }: Props) {
  const turns = subZone?.chat_context?.recent_turns ?? [];
  const subZoneId = subZone?.sub_zone_id ?? null;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);
  const lastSubZoneIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!subZoneId) return;
    if (lastSubZoneIdRef.current === subZoneId) return;
    lastSubZoneIdRef.current = subZoneId;
    stickToBottomRef.current = true;
    window.requestAnimationFrame(() => {
      const node = containerRef.current;
      if (!node) return;
      node.scrollTop = node.scrollHeight;
    });
  }, [subZoneId]);

  useEffect(() => {
    if (!subZoneId || turns.length === 0 || !stickToBottomRef.current) return;
    window.requestAnimationFrame(() => {
      const node = containerRef.current;
      if (!node) return;
      node.scrollTop = node.scrollHeight;
    });
  }, [subZoneId, turns.length]);

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
          <p>{subZone.name} 的历史回合会持续保存，并作为当前地区的长期叙事参考。</p>
        </div>
      </header>
      <div ref={containerRef} className="subzone-context-list" onScroll={onScroll}>
        {turns.map((turn) => {
          const visibleEvents = turn.events.filter((event) => !HIDDEN_EVENT_KINDS.has(event.event_kind));
          const passiveTurn = turn.player_mode === 'passive' && !turn.player_action && !turn.player_speech;
          return (
            <article key={turn.turn_id} className="subzone-context-turn">
              <div className="subzone-context-turn-header">
                <strong>{turn.world_time_text}</strong>
                <div className="subzone-context-meta">
                  <span>{turn.player_mode === 'passive' ? '自动推进' : '主动回合'}</span>
                  {turn.active_encounter_title && (
                    <span>
                      遭遇: {turn.active_encounter_title}
                      {turn.active_encounter_status ? ` / ${turn.active_encounter_status}` : ''}
                    </span>
                  )}
                </div>
              </div>
              <div className="subzone-context-turn-body">
                {passiveTurn ? (
                  <p>
                    <strong>玩家:</strong>
                    本轮选择观察与等待（自动推进）
                  </p>
                ) : (
                  <>
                    {turn.player_action && (
                      <p>
                        <strong>动作:</strong>
                        {turn.player_action}
                      </p>
                    )}
                    {turn.player_speech && (
                      <p>
                        <strong>语言:</strong>
                        {turn.player_speech}
                      </p>
                    )}
                  </>
                )}
                {turn.gm_narration && (
                  <p>
                    <strong>GM:</strong>
                    {turn.gm_narration}
                  </p>
                )}
              </div>
              {visibleEvents.length > 0 && (
                <ul className="subzone-context-events">
                  {visibleEvents.map((event, index) => (
                    <li key={`${turn.turn_id}_${event.actor_id || event.actor_name}_${index}`} className="subzone-context-event">
                      <strong>
                        {EVENT_LABEL[event.event_kind]}
                        {event.actor_name ? ` / ${event.actor_name}` : ''}
                      </strong>
                      <span>{event.content}</span>
                    </li>
                  ))}
                </ul>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
