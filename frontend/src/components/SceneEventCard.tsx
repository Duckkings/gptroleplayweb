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
  public_round_resolution: 'GM 结算',
  public_actor_resolution: '公开轮次',
  public_targeted_npc_reply: '目标 NPC 回应',
  public_bystander_reaction: '围观反应',
  team_public_reaction: '队友反应',
  public_turn_phase: '公开回合阶段',
  public_turn_initiative: '抢先顺序',
  public_turn_actor_action: '公开回合行动',
  public_turn_actor_resolution: '公开回合结算',
  public_turn_situation: '事态推进',
  public_turn_round_end: '回合结束',
  public_turn_relation_update: 'NPC 态度变化',
  public_turn_team_update: '队友态度变化',
  public_turn_environment_update: '环境风险变化',
  role_desire_surface: '角色欲望',
  companion_story_surface: '队友故事',
  reputation_update: '地区声望',
  encounter_started: '遭遇触发',
  encounter_progress: '遭遇推进',
  encounter_resolution: '遭遇结算',
  encounter_background: '遭遇背景',
  encounter_situation_update: '局势变化',
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
        <p>本步骤无需检定</p>
      </div>
    );
  }
  return (
    <div className="scene-event-block">
      <span>检定</span>
      <div className="scene-event-kv-grid">
        <p>属性：{check.ability_used ?? '-'}</p>
        <p>修正：{formatModifier(check.ability_modifier)}</p>
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
            <p>修正：{formatModifier(typeof metadata.ability_modifier === 'number' ? metadata.ability_modifier : undefined)}</p>
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

function renderGenericCard({
  label,
  actorName,
  content,
  compact,
}: {
  label: string;
  actorName?: string;
  content: string;
  compact: boolean;
}) {
  return (
    <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
      <header className="scene-event-card-header">
        <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
      </header>
      <div className="scene-event-card-body">
        <p>{content}</p>
      </div>
    </article>
  );
}

export function SceneEventCard({ event, compact = false }: Props) {
  const kind = eventKindOf(event);
  const label = LABEL_MAP[kind] ?? kind;
  const actorName = event.actor_name?.trim();
  const metadata = event.metadata ?? {};

  if (kind === 'public_turn_phase' || kind === 'public_turn_initiative' || kind === 'public_turn_situation' || kind === 'public_turn_round_end') {
    return renderGenericCard({ label, actorName, content: event.content, compact });
  }

  if (kind === 'public_turn_relation_update') {
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          <div className="scene-event-block">
            <span>变化</span>
            <p>{event.content}</p>
          </div>
          <div className="scene-event-kv-grid">
            <p>角色：{String(metadata.name ?? '-')}</p>
            <p>关系：{String(metadata.before_tag ?? '-')} -&gt; {String(metadata.after_tag ?? '-')}</p>
            <p>增量：{formatDelta(typeof metadata.relation_delta === 'number' ? metadata.relation_delta : undefined)}</p>
          </div>
          {metadata.reaction_text && (
            <div className="scene-event-block">
              <span>反应</span>
              <p>{String(metadata.reaction_text)}</p>
            </div>
          )}
        </div>
      </article>
    );
  }

  if (kind === 'public_turn_team_update') {
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          <div className="scene-event-block">
            <span>变化</span>
            <p>{event.content}</p>
          </div>
          <div className="scene-event-kv-grid">
            <p>
              好感：{typeof metadata.affinity_before === 'number' ? metadata.affinity_before : '-'} -&gt;{' '}
              {typeof metadata.affinity_after === 'number' ? metadata.affinity_after : '-'} ({formatDelta(typeof metadata.affinity_delta === 'number' ? metadata.affinity_delta : undefined)})
            </p>
            <p>
              信任：{typeof metadata.trust_before === 'number' ? metadata.trust_before : '-'} -&gt;{' '}
              {typeof metadata.trust_after === 'number' ? metadata.trust_after : '-'} ({formatDelta(typeof metadata.trust_delta === 'number' ? metadata.trust_delta : undefined)})
            </p>
          </div>
          {metadata.reaction_text && (
            <div className="scene-event-block">
              <span>反应</span>
              <p>{String(metadata.reaction_text)}</p>
            </div>
          )}
        </div>
      </article>
    );
  }

  if (kind === 'public_turn_environment_update') {
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
          <div className="scene-event-kv-grid">
            <p>环境位移：{formatDelta(typeof metadata.environment_shift === 'number' ? metadata.environment_shift : undefined)}</p>
            <p>风险：{String(metadata.environment_risk_level_before ?? '-')} -&gt; {String(metadata.environment_risk_level_after ?? '-')}</p>
          </div>
        </div>
      </article>
    );
  }

  if (kind === 'public_turn_actor_resolution') {
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
          <div className="scene-event-kv-grid">
            <p>判定：{String(metadata.check_outcome ?? '-')}</p>
            <p>规则：{String(metadata.resolution_rule ?? '-')}</p>
          </div>
        </div>
      </article>
    );
  }

  if (kind === 'public_turn_actor_action') {
    return renderGenericCard({ label, actorName, content: event.content, compact });
  }

  if (kind === 'public_actor_action') {
    const actorMetadata = asActorActionMetadata(event.metadata);
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          {actorMetadata.affiliation_label && (
            <div className="scene-event-inline-tags">
              <span className="scene-event-tag">{actorMetadata.affiliation_label}</span>
            </div>
          )}
          {actorMetadata.external_action_narration && (
            <div className="scene-event-block">
              <span>外在行为</span>
              <p>{actorMetadata.external_action_narration}</p>
            </div>
          )}
          {actorMetadata.speech_line && (
            <div className="scene-event-block">
              <span>角色语言</span>
              <p>{actorMetadata.speech_line}</p>
            </div>
          )}
          {!actorMetadata.external_action_narration && !actorMetadata.speech_line && (
            <div className="scene-event-block">
              <span>动作</span>
              <p>{event.content}</p>
            </div>
          )}
          {actorMetadata.checked_action_label && (
            <div className="scene-event-block">
              <span>检定行为</span>
              <p>{actorMetadata.checked_action_label}</p>
            </div>
          )}
          {renderCheckBlock(actorMetadata.check_result)}
          {actorMetadata.gm_result_summary && (
            <div className="scene-event-block">
              <span>GM 结果</span>
              <p>{actorMetadata.gm_result_summary}</p>
            </div>
          )}
        </div>
      </article>
    );
  }

  if (kind === 'public_round_resolution') {
    const roundMetadata = asRoundResolutionMetadata(event.metadata);
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          <div className="scene-event-block">
            <span>摘要</span>
            <p>{event.content}</p>
          </div>
          {(typeof roundMetadata.candidate_count === 'number' || typeof roundMetadata.reputation_score === 'number') && (
            <div className="scene-event-kv-grid">
              {typeof roundMetadata.candidate_count === 'number' && <p>参与角色：{roundMetadata.candidate_count}</p>}
              {typeof roundMetadata.reputation_score === 'number' && <p>地区声望：{roundMetadata.reputation_score}</p>}
            </div>
          )}
        </div>
      </article>
    );
  }

  if (kind === 'public_actor_resolution') {
    const actorResolution = asActorResolutionMetadata(event.metadata);
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
          <div className="scene-event-kv-grid">
            <p>局势：{formatDelta(actorResolution.situation_delta)}</p>
            <p>关系：{formatDelta(actorResolution.relation_delta)}</p>
            <p>声望：{formatDelta(actorResolution.reputation_delta)}</p>
          </div>
        </div>
      </article>
    );
  }

  if (kind === 'encounter_situation_update') {
    const situationMetadata = asSituationMetadata(event.metadata);
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          <div className="scene-event-kv-grid">
            {typeof situationMetadata.situation_value_before === 'number' && <p>结算前：{situationMetadata.situation_value_before}/100</p>}
            <p>玩家：{formatDelta(situationMetadata.player_situation_delta)}</p>
            <p>公开行动：{formatDelta(situationMetadata.public_actor_situation_delta_total)}</p>
            <p>世界推进：{formatDelta(situationMetadata.world_push_situation_delta_total)}</p>
            <p>合计：{formatDelta(situationMetadata.turn_total_delta ?? situationMetadata.situation_delta)}</p>
            {typeof (situationMetadata.situation_value_after ?? situationMetadata.situation_value) === 'number' && (
              <p>结算后：{situationMetadata.situation_value_after ?? situationMetadata.situation_value}/100</p>
            )}
          </div>
          <div className="scene-event-block">
            <span>结果</span>
            <p>{event.content}</p>
          </div>
        </div>
      </article>
    );
  }

  if (kind === 'encounter_world_push') {
    const worldPushMetadata = asWorldPushMetadata(event.metadata);
    return (
      <article className={`scene-event-card ${compact ? 'compact' : ''}`}>
        <header className="scene-event-card-header">
          <strong>{actorName ? `${label} / ${actorName}` : label}</strong>
        </header>
        <div className="scene-event-card-body">
          <div className="scene-event-block">
            <span>推进</span>
            <p>{event.content}</p>
          </div>
          <div className="scene-event-kv-grid">
            {worldPushMetadata.target_location_label && <p>地点：{worldPushMetadata.target_location_label}</p>}
            {worldPushMetadata.opened_window && <p>窗口：{worldPushMetadata.opened_window}</p>}
            {worldPushMetadata.pressure_note && <p>压力：{worldPushMetadata.pressure_note}</p>}
            {worldPushMetadata.spawned_npc_name && <p>新角色：{worldPushMetadata.spawned_npc_name}</p>}
          </div>
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
          <div className="scene-event-kv-grid">
            <p>来源：{String(metadata.source_label ?? actorName ?? '-')}</p>
            <p>属性：{String(metadata.ability_used ?? '-')}</p>
            <p>DC：{typeof metadata.dc === 'number' ? metadata.dc : '-'}</p>
          </div>
          {metadata.threatened_consequence && (
            <div className="scene-event-block">
              <span>风险</span>
              <p>{String(metadata.threatened_consequence)}</p>
            </div>
          )}
        </div>
      </article>
    );
  }

  if (kind === 'player_reaction_result') {
    return renderPlayerReactionResult(event, compact, actorName);
  }

  return renderGenericCard({ label, actorName, content: event.content, compact });
}
