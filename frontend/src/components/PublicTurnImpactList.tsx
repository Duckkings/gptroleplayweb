import type { PublicTurnImpact, PublicTurnRelationDelta, PublicTurnTeamAffinityDelta } from '../types/app';

type Props = {
  impacts: PublicTurnImpact[];
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

export function PublicTurnImpactList({ impacts }: Props) {
  if (impacts.length === 0) return null;

  return (
    <section className="chat-interactions">
      <h3>Round Impacts</h3>
      <div className="public-turn-impact-list">
        {impacts.map((impact) => (
          <article key={`${impact.actor_id}_${impact.action_summary}`} className="scene-event-card compact">
            <header className="scene-event-card-header">
              <strong>{impact.actor_name}</strong>
            </header>
            <div className="scene-event-card-body">
              <p>{impact.action_summary}</p>
              <div className="scene-event-kv-grid">
                <p>Check: {impact.check_outcome || '-'}</p>
                {impact.situation_delta !== 0 && <p>Situation: {formatSigned(impact.situation_delta)}</p>}
                {impact.zone_reputation_delta !== 0 && <p>Reputation: {formatSigned(impact.zone_reputation_delta)}</p>}
                {impact.environment_shift !== 0 && <p>Environment: {formatSigned(impact.environment_shift)}</p>}
              </div>

              {impact.relation_deltas.length > 0 && (
                <div className="scene-event-block">
                  <span>NPC Reactions</span>
                  <div className="scene-event-kv-grid">{impact.relation_deltas.map(renderNpcReaction)}</div>
                </div>
              )}

              {impact.team_affinity_deltas.length > 0 && (
                <div className="scene-event-block">
                  <span>Team Reactions</span>
                  <div className="scene-event-kv-grid">{impact.team_affinity_deltas.map(renderTeamReaction)}</div>
                </div>
              )}

              {impact.hp_changes.length > 0 && (
                <div className="scene-event-block">
                  <span>HP Changes</span>
                  <div className="scene-event-kv-grid">
                    {impact.hp_changes.map((row) => (
                      <p key={`${row.target_id}_${row.hp_delta}`}>
                        {row.target_name}: {row.hp_before} -&gt; {row.hp_after} ({formatSigned(row.hp_delta)})
                      </p>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
