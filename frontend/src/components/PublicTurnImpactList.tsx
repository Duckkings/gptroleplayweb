import type { PublicTurnImpact } from '../types/app';

type Props = {
  impacts: PublicTurnImpact[];
};

function formatSigned(value: number): string {
  return `${value >= 0 ? '+' : ''}${value}`;
}

export function PublicTurnImpactList({ impacts }: Props) {
  if (impacts.length === 0) return null;

  return (
    <section className="chat-interactions">
      <h3>本轮影响</h3>
      <div className="public-turn-impact-list">
        {impacts.map((impact) => (
          <article key={`${impact.actor_id}_${impact.action_summary}`} className="scene-event-card compact">
            <header className="scene-event-card-header">
              <strong>{impact.actor_name}</strong>
            </header>
            <div className="scene-event-card-body">
              <p>{impact.action_summary}</p>
              <div className="scene-event-kv-grid">
                <p>检定：{impact.check_outcome || '-'}</p>
                <p>局势：{formatSigned(impact.situation_delta)}</p>
                <p>声望：{formatSigned(impact.zone_reputation_delta)}</p>
                <p>环境：{formatSigned(impact.environment_shift)}</p>
              </div>

              {impact.relation_deltas.length > 0 && (
                <div className="scene-event-block">
                  <span>NPC 反应</span>
                  <div className="scene-event-kv-grid">
                    {impact.relation_deltas.map((row) => (
                      <p key={row.role_id}>
                        {row.name}：{row.before_tag} -&gt; {row.after_tag} ({formatSigned(row.relation_delta)})
                        {row.reaction_text ? ` / ${row.reaction_text}` : ''}
                      </p>
                    ))}
                  </div>
                </div>
              )}

              {impact.team_affinity_deltas.length > 0 && (
                <div className="scene-event-block">
                  <span>队友反应</span>
                  <div className="scene-event-kv-grid">
                    {impact.team_affinity_deltas.map((row) => (
                      <p key={row.member_role_id}>
                        {row.name}：好感 {row.affinity_before} -&gt; {row.affinity_after} ({formatSigned(row.affinity_delta)}) / 信任{' '}
                        {row.trust_before} -&gt; {row.trust_after} ({formatSigned(row.trust_delta)})
                        {row.reaction_text ? ` / ${row.reaction_text}` : ''}
                      </p>
                    ))}
                  </div>
                </div>
              )}

              {impact.hp_changes.length > 0 && (
                <div className="scene-event-block">
                  <span>HP 变化</span>
                  <div className="scene-event-kv-grid">
                    {impact.hp_changes.map((row) => (
                      <p key={`${row.target_id}_${row.hp_delta}`}>
                        {row.target_name}：{row.hp_before} -&gt; {row.hp_after} ({formatSigned(row.hp_delta)})
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
