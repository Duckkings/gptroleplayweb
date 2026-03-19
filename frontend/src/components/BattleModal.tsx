import type { BattleSandboxState } from '../types/app';
import { BattleActionPanel } from './BattleActionPanel';
import { BattleCombatantCard } from './BattleCombatantCard';
import { BattleLogPanel } from './BattleLogPanel';
import { BattleTurnOrder } from './BattleTurnOrder';

type Props = {
  open: boolean;
  battle: BattleSandboxState | null;
  busy?: boolean;
  onClose: () => void;
  onMinimize?: () => void;
  onAction: (payload: {
    action_kind: 'attack' | 'defend' | 'move' | 'disengage' | 'escape' | 'use_item' | 'observe' | 'end_turn';
    target_combatant_id?: string | null;
    destination_band?: 'engaged' | 'near' | 'far' | 'remote' | null;
    item_id?: string | null;
  }) => void;
  onContinueAi: (aiPacing: 'step' | 'auto') => void;
  onSetAiPacing: (aiPacing: 'step' | 'auto') => void;
  onEndBattle: () => void;
};

export function BattleModal({ open, battle, busy = false, onClose, onMinimize, onAction, onContinueAi, onSetAiPacing, onEndBattle }: Props) {
  if (!open || !battle) return null;
  const activeId = battle.combat_state.active_combatant_id;
  const activeCombatant = battle.combat_state.combatants.find((item) => item.combatant_id === activeId) ?? null;

  return (
    <div className="modal-mask">
      <div className="modal-card battle-modal">
        <header className="battle-modal-header">
          <div>
            <h3>战斗测试</h3>
            <p>
              战场: {battle.battlefield.zone_name || '未知大区块'} / {battle.battlefield.sub_zone_name || '未知子区块'}
            </p>
            <p>
              回合 {battle.combat_state.round} | 当前行动者: {activeCombatant?.display_name ?? '未知'} | 战场掌控度: {battle.combat_state.momentum_value}
            </p>
            <p>状态: {battle.status} | AI 速度: {battle.ui_flags.ai_pacing === 'step' ? '逐单位暂停' : '自动连走'}</p>
          </div>
          <div className="actions">
            {onMinimize ? (
              <button onClick={onMinimize} disabled={busy}>
                暂时关闭
              </button>
            ) : null}
            <button onClick={onClose} disabled={busy || (battle.status !== 'ended' && battle.status !== 'cancelled')}>
              收起
            </button>
            <button onClick={onEndBattle} disabled={busy}>
              结束战斗测试
            </button>
          </div>
        </header>

        <BattleTurnOrder battle={battle} />

        <section className="battle-roster-grid">
          <div className="battle-panel">
            <h4>玩家方</h4>
            <div className="battle-combatant-list">
              <BattleCombatantCard combatant={battle.player_snapshot} active={battle.player_snapshot.combatant_id === activeId} />
              {battle.ally_snapshots.map((combatant) => (
                <BattleCombatantCard key={combatant.combatant_id} combatant={combatant} active={combatant.combatant_id === activeId} />
              ))}
            </div>
          </div>
          <div className="battle-panel">
            <h4>敌方</h4>
            <div className="battle-combatant-list">
              {battle.enemy_snapshots.map((combatant) => (
                <BattleCombatantCard key={combatant.combatant_id} combatant={combatant} active={combatant.combatant_id === activeId} />
              ))}
            </div>
          </div>
        </section>

        <BattleLogPanel steps={battle.battle_logs} />

        <section className="battle-panel">
          <div className="actions battle-ai-controls">
            <button
              className={battle.ui_flags.ai_pacing === 'step' ? 'active' : ''}
              onClick={() => onSetAiPacing('step')}
              disabled={busy}
            >
              逐单位暂停
            </button>
            <button
              className={battle.ui_flags.ai_pacing === 'auto' ? 'active' : ''}
              onClick={() => onSetAiPacing('auto')}
              disabled={busy}
            >
              自动连走
            </button>
            <button onClick={() => onContinueAi(battle.ui_flags.ai_pacing)} disabled={busy || battle.status !== 'awaiting_ai_continue'}>
              继续 AI 行动
            </button>
          </div>
        </section>

        {battle.status === 'awaiting_player_action' && <BattleActionPanel battle={battle} busy={busy} onAction={onAction} />}
        {battle.status === 'awaiting_player_roll' && (
          <section className="battle-panel">
            <h4>等待掷骰</h4>
            <p>
              当前检定: {battle.pending_roll?.action_name || battle.pending_roll?.roll_kind || '未知'} / {battle.pending_roll?.check_task || '未知'}
            </p>
            <p className="hint">请在弹出的骰子框里掷骰后继续。</p>
          </section>
        )}
        {battle.status === 'ended' && (
          <section className="battle-panel">
            <h4>战斗结束</h4>
            <p>结果: {battle.combat_state.winner_side ?? '未知'}</p>
          </section>
        )}
      </div>
    </div>
  );
}
