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
};

function formatSigned(value: number): string {
  return `${value >= 0 ? '+' : ''}${value}`;
}

function renderReactionText(action: string, speech: string, fallback: string): string | null {
  const cleanAction = action.trim();
  const cleanSpeech = speech.trim();
  if (cleanAction && cleanSpeech) {
    return `${cleanAction} / "${cleanSpeech}"`;
  }
  if (cleanAction) {
    return cleanAction;
  }
  if (cleanSpeech) {
    return `"${cleanSpeech}"`;
  }
  return fallback.trim() || null;
}

function renderReactionMeta(focusName?: string | null, speechTargetName?: string | null): string | null {
  const parts: string[] = [];
  if ((focusName ?? '').trim()) {
    parts.push(`focus=${focusName}`);
  }
  if ((speechTargetName ?? '').trim()) {
    parts.push(`to=${speechTargetName}`);
  }
  return parts.length ? parts.join(' / ') : null;
}

function renderCheck(check: PublicTurnSettlementCheck | null | undefined) {
  if (!check) {
    return <p className="hint">No formal check triggered.</p>;
  }
  return (
    <div className="public-turn-check-block">
      <p>{check.comparison_text}</p>
      <p>Outcome: {check.outcome_text}</p>
    </div>
  );
}

function renderNpcReaction(row: PublicTurnRelationDelta) {
  const reaction = renderReactionText(row.reaction_action, row.reaction_speech, row.reaction_text);
  const meta = renderReactionMeta(row.reaction_focus_actor_name, row.reaction_speech_target_name);
  return (
    <p key={row.role_id}>
      {row.name}: {row.before_tag} -&gt; {row.after_tag} ({formatSigned(row.relation_delta)})
      {row.reaction_tone ? ` / ${row.reaction_tone}` : ''}
      {meta ? ` / ${meta}` : ''}
      {reaction ? ` / ${reaction}` : ''}
    </p>
  );
}

function renderTeamReaction(row: PublicTurnTeamAffinityDelta) {
  const reaction = renderReactionText(row.reaction_action, row.reaction_speech, row.reaction_text);
  const meta = renderReactionMeta(row.reaction_focus_actor_name, row.reaction_speech_target_name);
  return (
    <p key={row.member_role_id}>
      {row.name}: Affinity {row.affinity_before} -&gt; {row.affinity_after} ({formatSigned(row.affinity_delta)}) / Trust {row.trust_before} -&gt;{' '}
      {row.trust_after} ({formatSigned(row.trust_delta)})
      {row.reaction_tone ? ` / ${row.reaction_tone}` : ''}
      {meta ? ` / ${meta}` : ''}
      {reaction ? ` / ${reaction}` : ''}
    </p>
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
    return <p className="hint">No extra structured consequence this turn.</p>;
  }

  return (
    <div className="public-turn-consequence-list">
      {(entry.situation_delta !== 0 || entry.zone_reputation_delta !== 0 || entry.environment_shift !== 0) && (
        <div className="scene-event-kv-grid">
          {entry.situation_delta !== 0 && <p>Situation: {formatSigned(entry.situation_delta)}</p>}
          {entry.zone_reputation_delta !== 0 && <p>Reputation: {formatSigned(entry.zone_reputation_delta)}</p>}
          {entry.environment_shift !== 0 && <p>Environment: {formatSigned(entry.environment_shift)}</p>}
        </div>
      )}
      {entry.relation_deltas.length > 0 && (
        <div className="scene-event-block">
          <span>NPC Reactions</span>
          <div className="scene-event-kv-grid">{entry.relation_deltas.map(renderNpcReaction)}</div>
        </div>
      )}
      {entry.team_affinity_deltas.length > 0 && (
        <div className="scene-event-block">
          <span>Team Reactions</span>
          <div className="scene-event-kv-grid">{entry.team_affinity_deltas.map(renderTeamReaction)}</div>
        </div>
      )}
      {entry.hp_changes.length > 0 && (
        <div className="scene-event-block">
          <span>HP Changes</span>
          <div className="scene-event-kv-grid">
            {entry.hp_changes.map((row) => (
              <p key={`${row.target_id}_${row.hp_delta}`}>
                {row.target_name}: {row.hp_before} -&gt; {row.hp_after} ({formatSigned(row.hp_delta)})
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function renderActorEntry(entry: PublicTurnSettlementEntry) {
  const emptyActorEntry = !entry.action_summary.trim() && !entry.speech_text.trim();
  const noActionResponse =
    entry.target_response_kind === 'no_action' && !entry.opposed_target_action && !entry.opposed_target_speech;
  const shouldRenderCheck = entry.interaction_exchange_kind !== 'non_world_exchange';
  return (
    <>
      <div className="scene-event-block">
        <span>Action</span>
        <p>{entry.action_summary || 'No visible action this turn.'}</p>
        {entry.action_target_name ? <p>Action Target: {entry.action_target_name}</p> : null}
        {entry.interaction_exchange_kind === 'alternated_exchange' ? <p>Exchange: Alternated interaction</p> : null}
      </div>
      {entry.speech_text.trim() && (
        <div className="scene-event-block">
          <span>Speech</span>
          <p>{entry.speech_text}</p>
          {entry.speech_target_name ? <p>Addressee: {entry.speech_target_name}</p> : null}
        </div>
      )}
      {(entry.opposed_target_action || entry.opposed_target_speech || noActionResponse) && (
        <div className="scene-event-block">
          <span>Target Response</span>
          {entry.opposed_target_name && <p>{entry.opposed_target_name}</p>}
          {entry.opposed_target_action && <p>{entry.opposed_target_action}</p>}
          {entry.opposed_target_speech && <p>{entry.opposed_target_speech}</p>}
          {noActionResponse ? <p>No action taken.</p> : null}
          {entry.opposed_target_speech_target_name ? <p>Addressee: {entry.opposed_target_speech_target_name}</p> : null}
        </div>
      )}
      {shouldRenderCheck ? (
        <div className="scene-event-block">
          <span>Check / Opposed</span>
          {renderCheck(entry.check)}
        </div>
      ) : null}
      {emptyActorEntry && <p className="hint">AI returned no visible action or speech this turn.</p>}
      <div className="scene-event-block">
        <span>Structured Consequences</span>
        {renderConsequences(entry)}
      </div>
    </>
  );
}

function renderGmEntry(entry: PublicTurnSettlementEntry) {
  const result = entry.gm_push_result;
  return (
    <>
      <div className="scene-event-block">
        <span>Environment / Atmosphere</span>
        <p>{entry.gm_resolution_summary || 'No extra GM text this round.'}</p>
      </div>
      {result && (
        <div className="scene-event-block">
          <span>d6 Push</span>
          <div className="scene-event-kv-grid">
            <p>Roll: {result.roll_d6}</p>
            <p>Outcome: {result.outcome_label || result.outcome_kind}</p>
            {result.environment_change_text && <p>Environment: {result.environment_change_text}</p>}
            {result.spawned_npc_name && <p>Intervention: {result.spawned_npc_name}</p>}
          </div>
        </div>
      )}
      <div className="scene-event-block">
        <span>Structured Consequences</span>
        {renderConsequences(entry)}
      </div>
    </>
  );
}

export function PublicTurnSettlementPane({ presentation }: Props) {
  const entries = presentation?.settlement_entries ?? [];

  return (
    <section className="public-turn-settlement-pane">
      <header className="public-turn-pane-header">
        <h3>结算区</h3>
        <p>Checks, opposed rolls, structured consequences, and the GM push appear here.</p>
      </header>

      <PublicTurnInitiativeTrack entries={presentation?.initiative_order ?? []} />

      <div className="public-turn-settlement-list">
        {entries.length === 0 && <p className="hint">No resolved actions yet this round.</p>}
        {entries.map((entry) => (
          <article key={entry.entry_id} className="scene-event-card public-turn-settlement-card">
            <header className="scene-event-card-header">
              <strong>
                #{entry.order_index + 1} {entry.actor_name}
              </strong>
              <span className="scene-event-tag">{entry.entry_kind === 'gm_push' ? 'gm_push' : entry.phase}</span>
            </header>
            <div className="scene-event-card-body">{entry.entry_kind === 'gm_push' ? renderGmEntry(entry) : renderActorEntry(entry)}</div>
          </article>
        ))}
      </div>
    </section>
  );
}
