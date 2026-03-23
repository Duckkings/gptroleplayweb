import type {
  PublicTurnPresentation,
  PublicTurnRelationDelta,
  PublicTurnSettlementCheck,
  PublicTurnSettlementEntry,
  PublicTurnTeamAffinityDelta,
} from '../types/app';
import { PublicTurnInitiativeTrack } from './PublicTurnInitiativeTrack';

type Props = {
  presentation: PublicTurnPresentation | null;
  roundActive?: boolean;
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

function renderCheck(check: PublicTurnSettlementCheck | null | undefined) {
  if (!check) return null;
  return (
    <div className="public-turn-check-block">
      <p>{check.comparison_text}</p>
      <p>{check.outcome_text}</p>
    </div>
  );
}

function renderNpcReaction(row: PublicTurnRelationDelta) {
  const reactionCopy = [cleanText(row.reaction_action), cleanText(row.reaction_speech)].filter(Boolean).join(' / ');
  return (
    <p key={row.role_id}>
      {row.name}: {row.before_tag} -&gt; {row.after_tag} ({formatSigned(row.relation_delta)})
      {reactionCopy ? ` / ${reactionCopy}` : ''}
    </p>
  );
}

function renderTeamReaction(row: PublicTurnTeamAffinityDelta) {
  const reactionCopy = [cleanText(row.reaction_action), cleanText(row.reaction_speech)].filter(Boolean).join(' / ');
  return (
    <p key={row.member_role_id}>
      {row.name}: 好感 {row.affinity_before} -&gt; {row.affinity_after} ({formatSigned(row.affinity_delta)}) / 信任 {row.trust_before} -&gt; {row.trust_after} ({formatSigned(row.trust_delta)})
      {reactionCopy ? ` / ${reactionCopy}` : ''}
    </p>
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
  return (
    <div className="public-turn-consequence-list">
      {(entry.situation_delta !== 0 || entry.zone_reputation_delta !== 0 || entry.environment_shift !== 0) ? (
        <div className="scene-event-kv-grid">
          {entry.situation_delta !== 0 ? <p>{roundActive ? '待写入局势' : '局势'} {formatSigned(entry.situation_delta)}</p> : null}
          {entry.zone_reputation_delta !== 0 ? <p>{roundActive ? '待写入声望' : '声望'} {formatSigned(entry.zone_reputation_delta)}</p> : null}
          {entry.environment_shift !== 0 ? <p>{roundActive ? '待写入环境' : '环境'} {formatSigned(entry.environment_shift)}</p> : null}
        </div>
      ) : null}
      {entry.relation_deltas.length > 0 ? (
        <div className="scene-event-block">
          <span>NPC 态度变化</span>
          <div className="scene-event-kv-grid">{entry.relation_deltas.map(renderNpcReaction)}</div>
        </div>
      ) : null}
      {entry.team_affinity_deltas.length > 0 ? (
        <div className="scene-event-block">
          <span>队友态度变化</span>
          <div className="scene-event-kv-grid">{entry.team_affinity_deltas.map(renderTeamReaction)}</div>
        </div>
      ) : null}
      {entry.hp_changes.length > 0 ? (
        <div className="scene-event-block">
          <span>伤害结算</span>
          <div className="scene-event-kv-grid">
            {entry.hp_changes.map((row) => (
              <p key={`${row.target_id}_${row.hp_before}_${row.hp_after}`}>
                {row.target_name}: HP {row.hp_before} -&gt; {row.hp_after} ({formatSigned(row.hp_delta)})
              </p>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function renderDialogueBubbles(entry: PublicTurnSettlementEntry) {
  const actorAction = cleanText(entry.action_summary);
  const actorSpeech = cleanText(entry.speech_text);
  const targetAction = cleanText(entry.opposed_target_action);
  const targetSpeech = cleanText(entry.opposed_target_speech);
  const outcome = outcomeTextOf(entry);

  return (
    <div className="public-turn-dialogue-list">
      {actorAction || actorSpeech ? (
        <section className="public-turn-dialogue-box actor">
          <header>{entry.actor_name}</header>
          {actorAction ? <p><strong>行为:</strong>{actorAction}</p> : null}
          {actorSpeech ? <p><strong>语言:</strong>{actorSpeech}</p> : null}
        </section>
      ) : null}
      {targetAction || targetSpeech ? (
        <section className="public-turn-dialogue-box target">
          <header>{targetNameOf(entry) || '回应方'}</header>
          {targetAction ? <p><strong>回应行为:</strong>{targetAction}</p> : null}
          {targetSpeech ? <p><strong>回应语言:</strong>{targetSpeech}</p> : null}
        </section>
      ) : null}
      {outcome ? (
        <section className="public-turn-dialogue-box outcome">
          <header>结算结果</header>
          <p>{outcome}</p>
        </section>
      ) : null}
    </div>
  );
}

function renderActorEntry(entry: PublicTurnSettlementEntry, roundActive: boolean) {
  return (
    <>
      {renderDialogueBubbles(entry)}
      {entry.check || entry.followup_check ? (
        <div className="scene-event-block">
          <span>检定 / 对抗</span>
          {entry.check ? renderCheck(entry.check) : null}
          {entry.followup_check ? (
            <div className="public-turn-check-followup">
              <p><strong>后续信息检定</strong></p>
              {renderCheck(entry.followup_check)}
            </div>
          ) : null}
        </div>
      ) : null}
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
          <div className="scene-event-kv-grid">
            <p>点数 {result.roll_d6}</p>
            <p>结果 {result.outcome_label || result.outcome_kind}</p>
            {cleanText(result.environment_change_text) ? <p>环境 {cleanText(result.environment_change_text)}</p> : null}
            {cleanText(result.spawned_npc_name) ? <p>介入者 {cleanText(result.spawned_npc_name)}</p> : null}
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

export function PublicTurnSettlementPane({ presentation, roundActive = false }: Props) {
  const entries = presentation?.settlement_entries ?? [];

  return (
    <section className="public-turn-settlement-pane">
      <header className="public-turn-pane-header">
        <h3>回合结算</h3>
        <p>每个角色单独一张卡，展示行为、回应、检定和后果。</p>
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
                  #{entry.order_index + 1} {entry.actor_name}{targetName ? ` 对 ${targetName}` : ''}
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
    </section>
  );
}
