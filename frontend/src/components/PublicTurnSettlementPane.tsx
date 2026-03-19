import type { PublicTurnPresentation, PublicTurnSettlementCheck, PublicTurnSettlementEntry } from '../types/app';
import { PublicTurnInitiativeTrack } from './PublicTurnInitiativeTrack';

type Props = {
  presentation: PublicTurnPresentation | null;
};

function formatSigned(value: number): string {
  return `${value >= 0 ? '+' : ''}${value}`;
}

function renderCheck(check: PublicTurnSettlementCheck | null | undefined) {
  if (!check) {
    return <p className="hint">本行动未触发正式检定。</p>;
  }
  return (
    <div className="public-turn-check-block">
      <p>{check.comparison_text}</p>
      <p>结果：{check.outcome_text}</p>
    </div>
  );
}

function renderConsequences(entry: PublicTurnSettlementEntry) {
  const hasConsequences =
    entry.situation_delta !== 0 ||
    entry.zone_reputation_delta !== 0 ||
    entry.environment_shift !== 0 ||
    entry.relation_deltas.length > 0 ||
    entry.team_affinity_deltas.length > 0 ||
    entry.hp_changes.length > 0;

  if (!hasConsequences) {
    return <p className="hint">本次行动没有额外数值结算。</p>;
  }

  return (
    <div className="public-turn-consequence-list">
      {(entry.situation_delta !== 0 || entry.zone_reputation_delta !== 0 || entry.environment_shift !== 0) && (
        <div className="scene-event-kv-grid">
          <p>局势：{formatSigned(entry.situation_delta)}</p>
          <p>地区声望：{formatSigned(entry.zone_reputation_delta)}</p>
          <p>环境偏移：{formatSigned(entry.environment_shift)}</p>
        </div>
      )}
      {entry.relation_deltas.length > 0 && (
        <div className="scene-event-block">
          <span>NPC 反应</span>
          <div className="scene-event-kv-grid">
            {entry.relation_deltas.map((row) => (
              <p key={row.role_id}>
                {row.name}：{row.before_tag} -&gt; {row.after_tag} ({formatSigned(row.relation_delta)})
                {row.reaction_text ? ` / ${row.reaction_text}` : ''}
              </p>
            ))}
          </div>
        </div>
      )}
      {entry.team_affinity_deltas.length > 0 && (
        <div className="scene-event-block">
          <span>队友反应</span>
          <div className="scene-event-kv-grid">
            {entry.team_affinity_deltas.map((row) => (
              <p key={row.member_role_id}>
                {row.name}：好感 {row.affinity_before} -&gt; {row.affinity_after} ({formatSigned(row.affinity_delta)}) / 信任 {row.trust_before} -&gt;{' '}
                {row.trust_after} ({formatSigned(row.trust_delta)})
                {row.reaction_text ? ` / ${row.reaction_text}` : ''}
              </p>
            ))}
          </div>
        </div>
      )}
      {entry.hp_changes.length > 0 && (
        <div className="scene-event-block">
          <span>HP 变化</span>
          <div className="scene-event-kv-grid">
            {entry.hp_changes.map((row) => (
              <p key={`${row.target_id}_${row.hp_delta}`}>
                {row.target_name}：{row.hp_before} -&gt; {row.hp_after} ({formatSigned(row.hp_delta)})
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function PublicTurnSettlementPane({ presentation }: Props) {
  const entries = presentation?.settlement_entries ?? [];

  return (
    <section className="public-turn-settlement-pane">
      <header className="public-turn-pane-header">
        <h3>纯结算区</h3>
        <p>检定、对抗、后果都只在这里显示。</p>
      </header>

      <PublicTurnInitiativeTrack entries={presentation?.initiative_order ?? []} />

      <div className="public-turn-settlement-list">
        {entries.length === 0 && <p className="hint">本轮尚未出现已结算行动。</p>}
        {entries.map((entry) => (
          <article key={entry.entry_id} className="scene-event-card public-turn-settlement-card">
            <header className="scene-event-card-header">
              <strong>
                #{entry.order_index + 1} {entry.actor_name}
              </strong>
              <span className="scene-event-tag">{entry.phase}</span>
            </header>
            <div className="scene-event-card-body">
              <div className="scene-event-block">
                <span>行为</span>
                <p>{entry.action_summary || '未填写行为描述。'}</p>
              </div>
              {entry.speech_text.trim() && (
                <div className="scene-event-block">
                  <span>语言</span>
                  <p>{entry.speech_text}</p>
                </div>
              )}
              {(entry.opposed_target_action || entry.opposed_target_speech) && (
                <div className="scene-event-block">
                  <span>对手回应</span>
                  {entry.opposed_target_name && <p>{entry.opposed_target_name}</p>}
                  {entry.opposed_target_action && <p>{entry.opposed_target_action}</p>}
                  {entry.opposed_target_speech && <p>{entry.opposed_target_speech}</p>}
                </div>
              )}
              <div className="scene-event-block">
                <span>检定 / 对抗</span>
                {renderCheck(entry.check)}
              </div>
              <div className="scene-event-block">
                <span>GM 描述</span>
                <p>{entry.gm_resolution_summary}</p>
              </div>
              <div className="scene-event-block">
                <span>结构化后果</span>
                {renderConsequences(entry)}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
