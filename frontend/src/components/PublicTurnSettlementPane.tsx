import type { ReactNode } from 'react';

import type {
  PublicTurnPresentation,
  PublicTurnRelationDelta,
  PublicTurnSettlementCheck,
  PublicTurnSettlementEntry,
  PublicTurnTeamAffinityDelta,
  PublicTurnWorldImpactType,
} from '../types/app';
import { PublicTurnInitiativeTrack } from './PublicTurnInitiativeTrack';

type Props = {
  presentation: PublicTurnPresentation | null;
  roundActive?: boolean;
  inlinePanel?: ReactNode;
};

function cleanText(value: string | null | undefined): string {
  return (value ?? '').trim();
}

function unwrapJsonText(value: string | null | undefined): string {
  const trimmed = cleanText(value);
  if (!trimmed) return '';
  const fenceMatch = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  const candidate = (fenceMatch?.[1] ?? trimmed).trim();
  if (!candidate.startsWith('{')) return candidate;
  try {
    const parsed = JSON.parse(candidate) as Record<string, unknown>;
    for (const key of ['outcome', 'outcome_description', 'outcome_narration']) {
      const next = parsed[key];
      if (typeof next === 'string' && next.trim()) {
        return next.trim();
      }
    }
  } catch {
    return trimmed;
  }
  return trimmed;
}

function formatSigned(value: number): string {
  return `${value >= 0 ? '+' : ''}${value}`;
}

function worldImpactLabel(value: PublicTurnWorldImpactType | string | null | undefined): string {
  if (value === 'world') return '世界影响';
  if (value === 'non_world') return '无世界影响';
  return '未标注';
}

function renderSingleImpactSummary(label: string, value: PublicTurnWorldImpactType | string | null | undefined) {
  return (
    <div className="public-turn-impact-summary">
      <span className={`public-turn-impact-pill ${value === 'world' ? 'world' : 'non-world'}`}>
        {label}：{worldImpactLabel(value)}
      </span>
    </div>
  );
}

function targetNameOf(entry: PublicTurnSettlementEntry): string {
  return (
    cleanText(entry.interaction_target_name) ||
    cleanText(entry.action_target_name) ||
    cleanText(entry.speech_target_name) ||
    cleanText(entry.opposed_target_name) ||
    cleanText(entry.check?.target_name) ||
    cleanText(entry.followup_check?.target_name) ||
    ''
  );
}

function outcomeTextOf(entry: PublicTurnSettlementEntry): string {
  const summary = unwrapJsonText(entry.gm_resolution_summary);
  if (summary) return summary;
  if (entry.followup_check?.comparison_text) return entry.followup_check.comparison_text;
  if (entry.check?.comparison_text) return entry.check.comparison_text;
  return '';
}

function checkOutcomeLabel(check: PublicTurnSettlementCheck): string {
  if (check.critical === 'critical_success') return '暴击成功';
  if (check.critical === 'critical_failure') return '暴击失败';
  return check.success ? '成功' : '失败';
}

function renderCheck(check: PublicTurnSettlementCheck | null | undefined) {
  if (!check) return null;
  return (
    <details className="public-turn-check-foldout">
      <summary>
        <span>检定 / 对抗</span>
        <strong>结果：{checkOutcomeLabel(check)}</strong>
      </summary>
      <div className="public-turn-check-body">
        <p>{check.comparison_text}</p>
        <p>{check.outcome_text}</p>
      </div>
    </details>
  );
}

function hasCounterResponse(entry: PublicTurnSettlementEntry): boolean {
  return Boolean(
    cleanText(entry.opposed_target_action) ||
      cleanText(entry.opposed_target_speech) ||
      entry.followup_check ||
      entry.target_response_kind !== 'no_action' ||
      entry.interaction_resolution === 'rejected_opposed' ||
      entry.interaction_resolution === 'attack_flow',
  );
}

function renderSourceActionCard(entry: PublicTurnSettlementEntry) {
  const actorAction = cleanText(entry.action_summary);
  const actorSpeech = cleanText(entry.speech_text);
  const targetName = targetNameOf(entry);

  return (
    <section className="public-turn-resolution-card source">
      <header className="public-turn-resolution-card-header">
        <strong>源动作结果</strong>
        <span>{entry.actor_name}</span>
      </header>
      {targetName ? <p className="public-turn-resolution-target">目标: {targetName}</p> : null}
      {renderSingleImpactSummary('源动作', entry.source_world_impact_type)}
      <div className="public-turn-dialogue-lines">
        {actorAction ? (
          <p>
            <strong>动作:</strong>
            {actorAction}
          </p>
        ) : null}
        {actorSpeech ? (
          <p>
            <strong>语言:</strong>
            {actorSpeech}
          </p>
        ) : null}
      </div>
      {renderCheck(entry.check)}
    </section>
  );
}

function renderCounterResponseCard(entry: PublicTurnSettlementEntry) {
  const targetAction = cleanText(entry.opposed_target_action);
  const targetSpeech = cleanText(entry.opposed_target_speech);
  const outcome = outcomeTextOf(entry);
  const targetName = targetNameOf(entry);

  return (
    <section className="public-turn-resolution-card counter">
      <header className="public-turn-resolution-card-header">
        <strong>反制结果</strong>
        <span>{targetName || '回应方'}</span>
      </header>
      {renderSingleImpactSummary('反制', entry.target_response_world_impact_type)}
      <div className="public-turn-dialogue-lines">
        {targetAction ? (
          <p>
            <strong>反制动作:</strong>
            {targetAction}
          </p>
        ) : null}
        {targetSpeech ? (
          <p>
            <strong>反制语言:</strong>
            {targetSpeech}
          </p>
        ) : null}
      </div>
      {entry.followup_check ? (
        <div className="public-turn-followup-check">
          <p><strong>后续检定</strong></p>
          {renderCheck(entry.followup_check)}
        </div>
      ) : null}
      {outcome ? (
        <section className="public-turn-dialogue-box outcome public-turn-resolution-outcome">
          <header>结算结论</header>
          <p>{outcome}</p>
        </section>
      ) : null}
    </section>
  );
}

function renderNpcReaction(row: PublicTurnRelationDelta) {
  const reactionAction = cleanText(row.reaction_action);
  const reactionSpeech = cleanText(row.reaction_speech);
  return (
    <article key={row.role_id} className="public-turn-reaction-card">
      <header>{row.name}</header>
      <div className="public-turn-reaction-meta">
        <p>
          {row.before_tag} -&gt; {row.after_tag} ({formatSigned(row.relation_delta)})
        </p>
        <p>情绪: {row.reaction_tone}</p>
      </div>
      <div className="public-turn-reaction-lines">
        {reactionAction ? <p><strong>行为:</strong>{reactionAction}</p> : null}
        {reactionSpeech ? <p><strong>语言:</strong>{reactionSpeech}</p> : null}
      </div>
    </article>
  );
}

function renderTeamReaction(row: PublicTurnTeamAffinityDelta) {
  const reactionAction = cleanText(row.reaction_action);
  const reactionSpeech = cleanText(row.reaction_speech);
  return (
    <article key={row.member_role_id} className="public-turn-reaction-card">
      <header>{row.name}</header>
      <div className="public-turn-reaction-meta">
        <p>
          好感 {row.affinity_before} -&gt; {row.affinity_after} ({formatSigned(row.affinity_delta)})
        </p>
        <p>
          信任 {row.trust_before} -&gt; {row.trust_after} ({formatSigned(row.trust_delta)})
        </p>
      </div>
      <div className="public-turn-reaction-lines">
        {reactionAction ? <p><strong>行为:</strong>{reactionAction}</p> : null}
        {reactionSpeech ? <p><strong>语言:</strong>{reactionSpeech}</p> : null}
      </div>
    </article>
  );
}

function renderConsequences(entry: PublicTurnSettlementEntry, roundActive: boolean) {
  const hasMeta =
    entry.situation_delta !== 0 ||
    entry.zone_reputation_delta !== 0 ||
    entry.environment_shift !== 0 ||
    entry.relation_deltas.length > 0 ||
    entry.team_affinity_deltas.length > 0 ||
    entry.hp_changes.length > 0;

  if (!hasMeta) return <p className="hint">本条结算没有额外结构化后果。</p>;

  const dataPills = [
    entry.situation_delta !== 0 ? (
      <p key="situation" className="public-turn-consequence-pill">
        {roundActive ? '待写入局势' : '局势'} {formatSigned(entry.situation_delta)}
      </p>
    ) : null,
    entry.zone_reputation_delta !== 0 ? (
      <p key="reputation" className="public-turn-consequence-pill">
        {roundActive ? '待写入声望' : '声望'} {formatSigned(entry.zone_reputation_delta)}
      </p>
    ) : null,
    entry.environment_shift !== 0 ? (
      <p key="environment" className="public-turn-consequence-pill">
        {roundActive ? '待写入环境' : '环境'} {formatSigned(entry.environment_shift)}
      </p>
    ) : null,
    ...entry.hp_changes.map((row) => (
      <p key={`${row.target_id}_${row.hp_before}_${row.hp_after}`} className="public-turn-consequence-pill">
        {row.target_name}: HP {row.hp_before} -&gt; {row.hp_after} ({formatSigned(row.hp_delta)})
      </p>
    )),
  ].filter(Boolean);

  return (
    <div className="public-turn-consequence-stack">
      {dataPills.length > 0 ? <div className="public-turn-consequence-inline">{dataPills}</div> : null}
      {entry.relation_deltas.length > 0 ? (
        <section className="public-turn-subpanel">
          <span>NPC 态度变化</span>
          <div className="public-turn-reaction-list">{entry.relation_deltas.map(renderNpcReaction)}</div>
        </section>
      ) : null}
      {entry.team_affinity_deltas.length > 0 ? (
        <section className="public-turn-subpanel">
          <span>队友态度变化</span>
          <div className="public-turn-reaction-list">{entry.team_affinity_deltas.map(renderTeamReaction)}</div>
        </section>
      ) : null}
    </div>
  );
}

function renderActorEntry(entry: PublicTurnSettlementEntry, roundActive: boolean) {
  return (
    <>
      <div className="public-turn-resolution-grid">
        {renderSourceActionCard(entry)}
        {hasCounterResponse(entry) ? renderCounterResponseCard(entry) : null}
      </div>
      <div className="scene-event-block">
        <span>{roundActive ? '待写入后果' : '结构化后果'}</span>
        {renderConsequences(entry, roundActive)}
      </div>
    </>
  );
}

function renderGmEntry(entry: PublicTurnSettlementEntry, roundActive: boolean) {
  const gmText = outcomeTextOf(entry) || '本轮没有额外 GM 推动。';
  const result = entry.gm_push_result;
  return (
    <>
      <section className="public-turn-dialogue-box outcome">
        <header>环境 / 氛围</header>
        <p>{gmText}</p>
      </section>
      {result ? (
        <div className="scene-event-block">
          <span>d6 推动</span>
          <div className="public-turn-consequence-inline">
            <p className="public-turn-consequence-pill">点数 {result.roll_d6}</p>
            <p className="public-turn-consequence-pill">结果 {result.outcome_label || result.outcome_kind}</p>
            {cleanText(result.environment_change_text) ? (
              <p className="public-turn-consequence-pill">环境 {cleanText(result.environment_change_text)}</p>
            ) : null}
            {cleanText(result.spawned_npc_name) ? (
              <p className="public-turn-consequence-pill">介入者 {cleanText(result.spawned_npc_name)}</p>
            ) : null}
          </div>
        </div>
      ) : null}
      <div className="scene-event-block">
        <span>{roundActive ? '待写入后果' : '结构化后果'}</span>
        {renderConsequences(entry, roundActive)}
      </div>
    </>
  );
}

export function PublicTurnSettlementPane({ presentation, roundActive = false, inlinePanel = null }: Props) {
  const entries = presentation?.settlement_entries ?? [];

  return (
    <section className="public-turn-settlement-pane">
      <header className="public-turn-pane-header">
        <h3>回合结算</h3>
        <p>这里只保留结算结果、检定和结构化后果，玩家输入会嵌在结算区内。</p>
        {roundActive ? <p className="hint">本轮仍在进行中，局势 / 声望 / 环境变化尚未正式写入。</p> : null}
      </header>

      <PublicTurnInitiativeTrack entries={presentation?.initiative_order ?? []} />

      <div className="public-turn-settlement-list">
        {entries.length === 0 ? <p className="hint">本轮还没有可展示的结算条目。</p> : null}
        {entries.map((entry) => {
          const targetName = targetNameOf(entry);
          return (
            <article key={entry.entry_id} className="scene-event-card public-turn-settlement-card">
              <header className="scene-event-card-header">
                <strong>
                  #{entry.order_index + 1} {entry.actor_name}
                  {targetName ? ` 对 ${targetName}` : ''}
                </strong>
                <span className="scene-event-tag">{entry.entry_kind === 'gm_push' ? 'GM 推动' : entry.phase}</span>
              </header>
              <div className="scene-event-card-body">
                {entry.entry_kind === 'gm_push' ? renderGmEntry(entry, roundActive) : renderActorEntry(entry, roundActive)}
              </div>
            </article>
          );
        })}
      </div>

      {inlinePanel ? <div className="public-turn-inline-slot">{inlinePanel}</div> : null}
    </section>
  );
}
