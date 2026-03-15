import type { CombatantState } from '../types/app';

type Props = {
  combatant: CombatantState;
  active?: boolean;
};

export function BattleCombatantCard({ combatant, active = false }: Props) {
  return (
    <article className={`battle-combatant-card ${combatant.side} ${active ? 'active' : ''}`}>
      <header>
        <strong>{combatant.display_name}</strong>
        <span>{combatant.source_kind === 'player' ? '玩家' : combatant.source_kind === 'team' ? '队友' : '敌人'}</span>
      </header>
      <p>
        HP {combatant.current_hp}/{combatant.max_hp}
        {combatant.temp_hp > 0 ? ` (+${combatant.temp_hp})` : ''} | AC {combatant.armor_class}
      </p>
      <p>
        站位 {combatant.position_band} | 攻击 {combatant.attack_bonus >= 0 ? `+${combatant.attack_bonus}` : combatant.attack_bonus}
      </p>
      <p>条件：{combatant.conditions.length > 0 ? combatant.conditions.join('、') : '无'}</p>
    </article>
  );
}
