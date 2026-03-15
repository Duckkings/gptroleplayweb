import type { BattleSandboxState } from '../types/app';

type Props = {
  battle: BattleSandboxState;
};

export function BattleTurnOrder({ battle }: Props) {
  const lookup = new Map(battle.combat_state.combatants.map((item) => [item.combatant_id, item]));
  return (
    <section className="battle-panel">
      <h4>先攻顺序</h4>
      <div className="battle-turn-order">
        {battle.combat_state.initiative_order.map((combatantId) => {
          const item = lookup.get(combatantId);
          if (!item) return null;
          const active = battle.combat_state.active_combatant_id === combatantId;
          return (
            <article key={combatantId} className={`battle-turn-chip ${active ? 'active' : ''}`}>
              <strong>{item.display_name}</strong>
              <span>先攻 {item.initiative}</span>
            </article>
          );
        })}
      </div>
    </section>
  );
}
