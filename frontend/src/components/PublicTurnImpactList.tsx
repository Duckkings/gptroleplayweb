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
                <p>检定: {impact.check_outcome || '-'}</p>
                <p>局势: {formatSigned(impact.situation_delta)}</p>
                <p>声望: {formatSigned(impact.zone_reputation_delta)}</p>
                <p>环境: {formatSigned(impact.environment_shift)}</p>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
