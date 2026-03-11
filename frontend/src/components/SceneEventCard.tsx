import type {
  EncounterSituationMetadata,
  JsonValue,
  PublicActorActionMetadata,
  PublicRoundResolutionMetadata,
  PublicRoundResolutionRow,
  SceneEvent,
  SubZoneChatTurnEvent,
} from '../types/app';

type BaseEvent = Pick<SceneEvent, 'kind' | 'actor_name' | 'content'> & {
  metadata?: Record<string, JsonValue>;
};

type TurnEvent = Pick<SubZoneChatTurnEvent, 'event_kind' | 'actor_name' | 'content'> & {
  metadata?: Record<string, JsonValue>;
};

type Props = {
  event: BaseEvent | TurnEvent;
  compact?: boolean;
};

const LABEL_MAP: Record<string, string> = {
  public_actor_action: '公开行动',
  public_round_resolution: 'GM结算',
  public_actor_resolution: '公开轮次',
  public_targeted_npc_reply: '公开目标回复',
  public_bystander_reaction: '旁观反应',
  team_public_reaction: '队友反应',
  role_desire_surface: '角色欲望',
  companion_story_surface: '队友故事',
  reputation_update: '区域声望',
  encounter_started: '遭遇触发',
  encounter_progress: '遭遇推进',
  encounter_resolution: '遭遇结算',
  encounter_background: '遭遇后台',
  encounter_situation_update: '局势值',
  npc_reply: 'NPC',
  team_reply: '队友',
  system_notice: '系统',
};

function eventKindOf(event: BaseEvent | TurnEvent): string {
  return 'kind' in event ? event.kind : event.event_kind;
}

function asActorActionMetadata(value: Record<string, JsonValue> | undefined): PublicActorActionMetadata {
  return (value ?? {}) as unknown as PublicActorActionMetadata;
}

function asRoundResolutionMetadata(value: Record<string, JsonValue> | undefined): PublicRoundResolutionMetadata {
  return (value ?? {}) as unknown as PublicRoundResolutionMetadata;
}

function asSituationMetadata(value: Record<string, JsonValue> | undefined): EncounterSituationMetadata {
  return (value ?? {}) as unknown as EncounterSituationMetadata;
}

function renderRows(rows: PublicRoundResolutionRow[] | undefined) {
  if (!rows || rows.length === 0) return null;
  return (
    <div className="scene-event-result-list">
      {rows.map((row, index) => (
        <article key={`${row.actor_id || row.actor_name}_${index}`} className="scene-event-result-row">
          <strong>
            {row.actor_name} / {row.result}
          </strong>
          {row.affected_object && <p>影响对象：{row.affected_object}</p>}
          {row.concrete_effect && <p>具体结果：{row.concrete_effect}</p>}
          {row.opened_opportunity && <p>留下机会：{row.opened_opportunity}</p>}
          {row.new_pressure && <p>新增压力：{row.new_pressure}</p>}
        </article>
      ))}
    </div>
  );
}

export function SceneEventCard({ event, compact = false }: Props) {
  const kind = eventKindOf(event);
  const label = LABEL_MAP[kind] ?? kind;
  const actorName = event.actor_name?.trim();

  if (kind === 'public_actor_action') {
    const metadata = asActorActionMetadata(event.metadata);
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          {metadata.external_action_narration && (
            <div className="scene-event-block">
              <span>外在行为</span>
              <p>{metadata.external_action_narration}</p>
            </div>
          )}
          {metadata.speech_line && (
            <div className="scene-event-block">
              <span>角色语言</span>
              <p>{metadata.speech_line}</p>
            </div>
          )}
          {metadata.visible_intent && (
            <div className="scene-event-block">
              <span>表面意图</span>
              <p>{metadata.visible_intent}</p>
            </div>
          )}
          {metadata.specific_threat && (
            <div className="scene-event-block">
              <span>眼前风险</span>
              <p>{metadata.specific_threat}</p>
            </div>
          )}
          {(metadata.private_goal || metadata.private_reason) && (
            <div className="scene-event-block debug">
              <span>调试信息</span>
              {metadata.private_goal && <p>内在目标：{metadata.private_goal}</p>}
              {metadata.private_reason && <p>内在原因：{metadata.private_reason}</p>}
            </div>
          )}
          {!metadata.external_action_narration && <p>{event.content}</p>}
        </div>
      </article>
    );
  }

  if (kind === 'public_round_resolution') {
    const metadata = asRoundResolutionMetadata(event.metadata);
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          <div className="scene-event-block">
            <span>结算摘要</span>
            <p>{event.content}</p>
          </div>
          {typeof metadata.situation_value_before === 'number' && typeof metadata.situation_value_after === 'number' && (
            <div className="scene-event-block">
              <span>局势变化</span>
              <p>
                {metadata.situation_value_before}/100 -&gt; {metadata.situation_value_after}/100
                {metadata.direction ? ` / ${metadata.direction}` : ''}
                {metadata.trend ? ` / ${metadata.trend}` : ''}
              </p>
            </div>
          )}
          {renderRows(metadata.result_rows)}
        </div>
      </article>
    );
  }

  if (kind === 'encounter_situation_update') {
    const metadata = asSituationMetadata(event.metadata);
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          {typeof metadata.situation_value === 'number' && (
            <div className="scene-event-block">
              <span>数值</span>
              <p>
                {metadata.situation_value}/100
                {typeof metadata.situation_delta === 'number' ? ` / ${metadata.situation_delta >= 0 ? '+' : ''}${metadata.situation_delta}` : ''}
                {metadata.direction ? ` / ${metadata.direction}` : ''}
              </p>
            </div>
          )}
          <div className="scene-event-block">
            <span>结果</span>
            <p>{event.content}</p>
          </div>
        </div>
      </article>
    );
  }

  return (
    <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
      <header className="scene-event-card-header">
        <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
      </header>
      <div className="scene-event-card-body">
        <p>{event.content}</p>
      </div>
    </article>
  );
}
