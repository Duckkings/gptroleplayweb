import type { PublicTurnInitiativeEntry } from '../types/app';

type Props = {
  entries: PublicTurnInitiativeEntry[];
};

export function PublicTurnInitiativeTrack({ entries }: Props) {
  if (entries.length === 0) {
    return null;
  }

  return (
    <section className="public-turn-initiative-track">
      <header className="public-turn-pane-header">
        <h4>抢先顺序</h4>
        <p>按敏捷修正 + d20 排序</p>
      </header>
      <div className="public-turn-initiative-list">
        {entries.map((entry) => (
          <article key={`${entry.actor_id}_${entry.order_index}`} className="public-turn-initiative-card">
            <strong>{entry.order_index + 1}. {entry.actor_name}</strong>
            <p>敏捷 {entry.dex_modifier >= 0 ? `+${entry.dex_modifier}` : entry.dex_modifier}</p>
            <p>d20 {entry.roll_d20} / 总值 {entry.total_initiative}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
