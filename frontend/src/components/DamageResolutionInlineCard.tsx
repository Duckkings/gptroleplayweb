import type { JsonValue, SceneEvent, SubZoneChatTurnEvent } from '../types/app';

type DamageEventLike =
  | Pick<SceneEvent, 'kind' | 'actor_name' | 'content'> & { metadata?: Record<string, JsonValue> }
  | Pick<SubZoneChatTurnEvent, 'event_kind' | 'actor_name' | 'content'> & { metadata?: Record<string, JsonValue> };

type Props = {
  event: DamageEventLike;
  compact?: boolean;
};

function eventKindOf(event: DamageEventLike): string {
  return 'kind' in event ? event.kind : event.event_kind;
}

function asString(value: JsonValue | undefined): string {
  return typeof value === 'string' ? value.trim() : '';
}

function asNumber(value: JsonValue | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function lifeStatusLabel(value: string): string {
  if (value === 'dead') return '死亡';
  if (value === 'dying') return '濒死';
  return '正常';
}

function damageTypeLabel(value: string): string {
  return value || '未注明';
}

export function isDamageResolutionEvent(event: DamageEventLike | null | undefined): boolean {
  if (!event) return false;
  return eventKindOf(event) === 'damage_resolution';
}

export function DamageResolutionInlineCard({ event, compact = false }: Props) {
  if (!isDamageResolutionEvent(event)) {
    return null;
  }
  const metadata = event.metadata ?? {};
  const sourceName = asString(metadata.source_actor_name) || event.actor_name?.trim() || '未知来源';
  const targetName = asString(metadata.target_actor_name) || '未知目标';
  const damage = asNumber(metadata.damage);
  const hpBefore = asNumber(metadata.hp_before);
  const hpAfter = asNumber(metadata.hp_after);
  const hpDelta = asNumber(metadata.hp_delta);
  const tempHpAbsorbed = asNumber(metadata.temp_hp_absorbed);
  const damageType = damageTypeLabel(asString(metadata.damage_type));
  const statusAfter = lifeStatusLabel(asString(metadata.life_status_after));
  const triggeredDeathSave = Boolean(metadata.triggered_death_save);
  const declaredDeath = Boolean(metadata.declared_death);

  return (
    <article className={`damage-resolution-card ${compact ? 'compact' : ''}`}>
      <header className="damage-resolution-header">
        <strong>伤害结算</strong>
        <span className="damage-resolution-badge">{statusAfter}</span>
      </header>
      <div className="damage-resolution-grid">
        <p>{sourceName} -&gt; {targetName}</p>
        <p>{damage ?? '-'} 点 {damageType}</p>
        <p>HP {hpBefore ?? '-'} -&gt; {hpAfter ?? '-'}</p>
        <p>变化 {typeof hpDelta === 'number' ? `${hpDelta >= 0 ? '+' : ''}${hpDelta}` : '-'}</p>
        {typeof tempHpAbsorbed === 'number' && tempHpAbsorbed > 0 ? <p>临时生命吸收 {tempHpAbsorbed}</p> : null}
        {triggeredDeathSave ? <p>已触发死亡豁免</p> : null}
        {declaredDeath ? <p>目标已死亡</p> : null}
      </div>
      {event.content?.trim() ? <p className="damage-resolution-copy">{event.content}</p> : null}
    </article>
  );
}
