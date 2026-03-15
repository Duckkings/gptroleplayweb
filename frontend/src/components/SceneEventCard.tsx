import type {
  EncounterSituationMetadata,
  EncounterWorldPushMetadata,
  JsonValue,
  PublicActorActionMetadata,
  PublicActorCheckResult,
  PublicActorResolutionMetadata,
  PublicRoundResolutionMetadata,
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
  encounter_world_push: '世界推进',
  player_reaction_triggered: '玩家反应检定',
  player_reaction_result: '玩家反应结果',
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

function asActorResolutionMetadata(value: Record<string, JsonValue> | undefined): PublicActorResolutionMetadata {
  return (value ?? {}) as unknown as PublicActorResolutionMetadata;
}

function asSituationMetadata(value: Record<string, JsonValue> | undefined): EncounterSituationMetadata {
  return (value ?? {}) as unknown as EncounterSituationMetadata;
}

function asWorldPushMetadata(value: Record<string, JsonValue> | undefined): EncounterWorldPushMetadata {
  return (value ?? {}) as unknown as EncounterWorldPushMetadata;
}

function formatModifier(value: number | undefined): string {
  const numberValue = typeof value === 'number' ? value : 0;
  return `${numberValue >= 0 ? '+' : ''}${numberValue}`;
}

function formatDelta(value: number | undefined): string {
  if (typeof value !== 'number') return '-';
  return `${value >= 0 ? '+' : ''}${value}`;
}

function formatOutcomeLabel(check: PublicActorCheckResult | undefined): string {
  if (!check || !check.requires_check) return '无需检定';
  if (check.critical === 'critical_success') return '大成功';
  if (check.critical === 'critical_failure') return '大失败';
  if (check.outcome_label) return check.outcome_label;
  return check.success ? '成功' : '失败';
}

function renderCheckBlock(check: PublicActorCheckResult | undefined) {
  if (!check || !check.requires_check) {
    return (
      <div className="scene-event-block">
        <span>结果</span>
        <p>本步无需检定</p>
      </div>
    );
  }
  return (
    <div className="scene-event-block">
      <span>结果</span>
      <div className="scene-event-kv-grid">
        <p>属性：{check.ability_used ?? '-'}</p>
        <p>调整值：{formatModifier(check.ability_modifier)}</p>
        <p>d20：{typeof check.dice_roll === 'number' ? check.dice_roll : '-'}</p>
        <p>总值：{typeof check.total_score === 'number' ? check.total_score : '-'}</p>
        <p>DC：{typeof check.dc === 'number' ? check.dc : '-'}</p>
        <p>结果：{formatOutcomeLabel(check)}</p>
      </div>
    </div>
  );
}

function renderPlayerReactionResult(event: BaseEvent | TurnEvent, compact: boolean, actorName?: string) {
  const metadata = event.metadata ?? {};
  const label = LABEL_MAP.player_reaction_result;
  const resultLabel =
    metadata.critical === 'critical_success'
      ? '大成功'
      : metadata.critical === 'critical_failure'
        ? '大失败'
        : metadata.success
          ? '成功'
          : '失败';
  return (
    <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
      <header className="scene-event-card-header">
        <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
      </header>
      <div className="scene-event-card-body">
        <div className="scene-event-block">
          <span>结果</span>
          <p>{event.content}</p>
        </div>
        <div className="scene-event-block">
          <span>检定摘要</span>
          <div className="scene-event-kv-grid">
            <p>属性：{String(metadata.ability_used ?? '-')}</p>
            <p>调整值：{formatModifier(typeof metadata.ability_modifier === 'number' ? metadata.ability_modifier : undefined)}</p>
            <p>d20：{typeof metadata.dice_roll === 'number' ? metadata.dice_roll : '-'}</p>
            <p>总值：{typeof metadata.total_score === 'number' ? metadata.total_score : '-'}</p>
            <p>DC：{typeof metadata.dc === 'number' ? metadata.dc : '-'}</p>
            <p>结果：{resultLabel}</p>
          </div>
        </div>
      </div>
    </article>
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
          {metadata.affiliation_label && (
            <div className="scene-event-inline-tags">
              <span className="scene-event-tag">{metadata.affiliation_label}</span>
            </div>
          )}
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
          {!metadata.external_action_narration && !metadata.speech_line && (
            <div className="scene-event-block">
              <span>动作</span>
              <p>{event.content}</p>
            </div>
          )}
          {metadata.checked_action_label && (
            <div className="scene-event-block">
              <span>检定行为</span>
              <p>{metadata.checked_action_label}</p>
            </div>
          )}
          {renderCheckBlock(metadata.check_result)}
          {metadata.gm_result_summary && (
            <div className="scene-event-block">
              <span>GM结果</span>
              <p>{metadata.gm_result_summary}</p>
            </div>
          )}
          {typeof metadata.situation_delta === 'number' && (
            <div className="scene-event-block">
              <span>局势值变化</span>
              <p>{formatDelta(metadata.situation_delta)}</p>
            </div>
          )}
          {(typeof metadata.team_affinity_before === 'number' ||
            typeof metadata.team_affinity_after === 'number' ||
            typeof metadata.team_trust_before === 'number' ||
            typeof metadata.team_trust_after === 'number') && (
            <div className="scene-event-block">
              <span>队友关系</span>
              <div className="scene-event-kv-grid">
                <p>
                  好感：{typeof metadata.team_affinity_before === 'number' ? metadata.team_affinity_before : '-'} -&gt;{' '}
                  {typeof metadata.team_affinity_after === 'number' ? metadata.team_affinity_after : '-'}
                  {typeof metadata.team_affinity_delta === 'number' ? ` (${formatDelta(metadata.team_affinity_delta)})` : ''}
                </p>
                <p>
                  信任：{typeof metadata.team_trust_before === 'number' ? metadata.team_trust_before : '-'} -&gt;{' '}
                  {typeof metadata.team_trust_after === 'number' ? metadata.team_trust_after : '-'}
                  {typeof metadata.team_trust_delta === 'number' ? ` (${formatDelta(metadata.team_trust_delta)})` : ''}
                </p>
              </div>
            </div>
          )}
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
          {(typeof metadata.candidate_count === 'number' || typeof metadata.reputation_score === 'number') && (
            <div className="scene-event-block">
              <span>摘要信息</span>
              <div className="scene-event-kv-grid">
                {typeof metadata.candidate_count === 'number' && <p>参与角色：{metadata.candidate_count}</p>}
                {typeof metadata.reputation_score === 'number' && <p>区域声望：{metadata.reputation_score}</p>}
              </div>
            </div>
          )}
          {(metadata.team_relation_rows?.length ?? 0) > 0 && (
            <div className="scene-event-block">
              <span>队友关系结算</span>
              <div className="scene-event-kv-grid">
                {metadata.team_relation_rows?.map((row) => (
                  <p key={row.role_id}>
                    {row.name}：好感 {row.affinity_before} -&gt; {row.affinity_after} ({formatDelta(row.affinity_delta)}) / 信任{' '}
                    {row.trust_before} -&gt; {row.trust_after} ({formatDelta(row.trust_delta)})
                  </p>
                ))}
              </div>
            </div>
          )}
        </div>
      </article>
    );
  }

  if (kind === 'public_actor_resolution') {
    const metadata = asActorResolutionMetadata(event.metadata);
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          <div className="scene-event-block">
            <span>结果</span>
            <p>{event.content}</p>
          </div>
          {(typeof metadata.situation_delta === 'number' ||
            typeof metadata.relation_delta === 'number' ||
            typeof metadata.reputation_delta === 'number') && (
            <div className="scene-event-block">
              <span>影响值</span>
              <p>
                {typeof metadata.situation_delta === 'number' ? `局势 ${formatDelta(metadata.situation_delta)}` : '局势 +0'}
                {typeof metadata.relation_delta === 'number' ? ` / 关系 ${formatDelta(metadata.relation_delta)}` : ''}
                {typeof metadata.reputation_delta === 'number' ? ` / 声望 ${formatDelta(metadata.reputation_delta)}` : ''}
              </p>
            </div>
          )}
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
          {typeof metadata.situation_value_before === 'number' && (
            <div className="scene-event-block">
              <span>结算前</span>
              <p>{metadata.situation_value_before}/100</p>
            </div>
          )}
          {(typeof metadata.player_situation_delta === 'number' ||
            typeof metadata.public_actor_situation_delta_total === 'number' ||
            typeof metadata.world_push_situation_delta_total === 'number' ||
            typeof metadata.turn_total_delta === 'number') && (
            <div className="scene-event-block">
              <span>本回合拆分</span>
              <div className="scene-event-kv-grid">
                <p>玩家：{formatDelta(metadata.player_situation_delta)}</p>
                <p>公开行动合计：{formatDelta(metadata.public_actor_situation_delta_total)}</p>
                <p>世界推进：{formatDelta(metadata.world_push_situation_delta_total)}</p>
                <p>本回合合计：{formatDelta(metadata.turn_total_delta ?? metadata.situation_delta)}</p>
              </div>
            </div>
          )}
          {(typeof metadata.situation_value_after === 'number' || typeof metadata.situation_value === 'number') && (
            <div className="scene-event-block">
              <span>结算后</span>
              <p>
                {(metadata.situation_value_after ?? metadata.situation_value)}/100
                {metadata.direction ? ` / ${metadata.direction}` : ''}
                {metadata.trend ? ` / ${metadata.trend}` : ''}
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

  if (kind === 'encounter_world_push') {
    const metadata = asWorldPushMetadata(event.metadata);
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          <div className="scene-event-block">
            <span>现场推进</span>
            <p>{event.content}</p>
          </div>
          {metadata.target_location_label && (
            <div className="scene-event-block">
              <span>关键地点</span>
              <p>{metadata.target_location_label}</p>
            </div>
          )}
          {metadata.opened_window && (
            <div className="scene-event-block">
              <span>新窗口</span>
              <p>{metadata.opened_window}</p>
            </div>
          )}
          {metadata.pressure_note && (
            <div className="scene-event-block">
              <span>新增压力</span>
              <p>{metadata.pressure_note}</p>
            </div>
          )}
          {metadata.spawned_npc_name && (
            <div className="scene-event-block">
              <span>新角色入场</span>
              <p>{metadata.spawned_npc_name}</p>
            </div>
          )}
        </div>
      </article>
    );
  }

  if (kind === 'player_reaction_triggered') {
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          <div className="scene-event-block">
            <span>威胁</span>
            <p>{event.content}</p>
          </div>
          <div className="scene-event-block">
            <span>检定</span>
            <div className="scene-event-kv-grid">
              <p>来源：{String(event.metadata?.source_label ?? actorName ?? '-')}</p>
              <p>属性：{String(event.metadata?.ability_used ?? '-')}</p>
              <p>DC：{typeof event.metadata?.dc === 'number' ? event.metadata.dc : '-'}</p>
            </div>
          </div>
          {event.metadata?.threatened_consequence && (
            <div className="scene-event-block">
              <span>风险</span>
              <p>{String(event.metadata.threatened_consequence)}</p>
            </div>
          )}
        </div>
      </article>
    );
  }

  if (kind === 'player_reaction_result') {
    return renderPlayerReactionResult(event, compact, actorName);
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
