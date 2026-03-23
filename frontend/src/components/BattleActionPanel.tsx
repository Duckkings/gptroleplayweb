import { useEffect, useMemo, useState } from 'react';
import type { BattleSandboxState, InventoryItem } from '../types/app';

type Props = {
  battle: BattleSandboxState;
  busy?: boolean;
  onAction: (payload: {
    action_kind: 'attack' | 'defend' | 'move' | 'disengage' | 'escape' | 'use_item' | 'observe' | 'end_turn';
    target_combatant_id?: string | null;
    destination_band?: 'engaged' | 'near' | 'far' | 'remote' | null;
    item_id?: string | null;
  }) => void;
};

function isUsableItem(item: InventoryItem): boolean {
  const text = `${item.item_type} ${item.name} ${item.effect}`.toLowerCase();
  return ['heal', 'healing', '治疗', '回复', 'potion'].some((keyword) => text.includes(keyword));
}

export function BattleActionPanel({ battle, busy = false, onAction }: Props) {
  const enemyTargets = useMemo(
    () => battle.combat_state.combatants.filter((item) => item.side === 'enemy_side' && item.alive && !item.escaped),
    [battle.combat_state.combatants],
  );
  const usableItems = useMemo(() => battle.player_snapshot.inventory_items.filter(isUsableItem), [battle.player_snapshot.inventory_items]);
  const [selectedTarget, setSelectedTarget] = useState<string>(enemyTargets[0]?.combatant_id ?? '');
  const [selectedBand, setSelectedBand] = useState<'engaged' | 'near' | 'far' | 'remote'>('near');
  const [selectedItem, setSelectedItem] = useState<string>(usableItems[0]?.item_id ?? '');

  useEffect(() => {
    setSelectedTarget(enemyTargets[0]?.combatant_id ?? '');
  }, [enemyTargets]);

  useEffect(() => {
    setSelectedItem(usableItems[0]?.item_id ?? '');
  }, [usableItems]);

  return (
    <section className="battle-panel">
      <h4>你的动作</h4>
      <div className="battle-action-grid">
        <label>
          <span>目标</span>
          <select value={selectedTarget} onChange={(e) => setSelectedTarget(e.target.value)} disabled={busy || enemyTargets.length === 0}>
            {enemyTargets.map((target) => (
              <option key={target.combatant_id} value={target.combatant_id}>
                {target.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>目标站位</span>
          <select value={selectedBand} onChange={(e) => setSelectedBand(e.target.value as 'engaged' | 'near' | 'far' | 'remote')} disabled={busy}>
            <option value="engaged">engaged</option>
            <option value="near">near</option>
            <option value="far">far</option>
            <option value="remote">remote</option>
          </select>
        </label>
        <label>
          <span>可用品</span>
          <select value={selectedItem} onChange={(e) => setSelectedItem(e.target.value)} disabled={busy || usableItems.length === 0}>
            {usableItems.map((item) => (
              <option key={item.item_id} value={item.item_id}>
                {item.name} x{item.quantity}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="actions battle-actions">
        <button onClick={() => onAction({ action_kind: 'attack', target_combatant_id: selectedTarget })} disabled={busy || !selectedTarget}>
          攻击
        </button>
        <button onClick={() => onAction({ action_kind: 'observe', target_combatant_id: selectedTarget })} disabled={busy || !selectedTarget}>
          观察
        </button>
        <button onClick={() => onAction({ action_kind: 'defend' })} disabled={busy}>
          防御
        </button>
        <button onClick={() => onAction({ action_kind: 'move', destination_band: selectedBand })} disabled={busy}>
          移动
        </button>
        <button onClick={() => onAction({ action_kind: 'disengage', destination_band: selectedBand })} disabled={busy}>
          脱离
        </button>
        <button onClick={() => onAction({ action_kind: 'escape' })} disabled={busy}>
          逃离
        </button>
        <button onClick={() => onAction({ action_kind: 'use_item', item_id: selectedItem })} disabled={busy || !selectedItem}>
          使用物品
        </button>
        <button onClick={() => onAction({ action_kind: 'end_turn' })} disabled={busy}>
          结束回合
        </button>
      </div>
    </section>
  );
}
