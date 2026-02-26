import { useEffect, useState } from 'react';
import type { ActionCheckResult, NpcRoleCard } from '../types/app';

type Props = {
  open: boolean;
  npcs: NpcRoleCard[];
  playerRoleId: string;
  lastResult: ActionCheckResult | null;
  onRun: (payload: { action_type: 'attack' | 'check' | 'item_use'; action_prompt: string; actor_role_id?: string }) => void;
  onClose: () => void;
};

export function ActionCheckPanel({ open, npcs, playerRoleId, lastResult, onRun, onClose }: Props) {
  const [actionType, setActionType] = useState<'attack' | 'check' | 'item_use'>('check');
  const [actionPrompt, setActionPrompt] = useState('');
  const [actorRoleId, setActorRoleId] = useState(playerRoleId);

  useEffect(() => {
    setActorRoleId(playerRoleId);
  }, [playerRoleId, open]);

  if (!open) return null;

  return (
    <section className="action-panel card">
      <header className="chat-header">
        <div>
          <h2>行为检定验证</h2>
          <p>用于验证 attack/check/item_use 的检定与时间消耗</p>
        </div>
        <button onClick={onClose}>关闭</button>
      </header>

      <div className="action-form">
        <label>
          行为类型
          <select value={actionType} onChange={(e) => setActionType(e.target.value as 'attack' | 'check' | 'item_use')}>
            <option value="attack">attack</option>
            <option value="check">check</option>
            <option value="item_use">item_use</option>
          </select>
        </label>

        <label>
          执行者
          <select value={actorRoleId} onChange={(e) => setActorRoleId(e.target.value)}>
            <option value={playerRoleId}>玩家（{playerRoleId}）</option>
            {npcs.map((npc) => (
              <option key={npc.role_id} value={npc.role_id}>
                {npc.name} ({npc.role_id})
              </option>
            ))}
          </select>
        </label>

        <label>
          行为描述
          <textarea
            value={actionPrompt}
            onChange={(e) => setActionPrompt(e.target.value)}
            placeholder="例如：我尝试说服守卫放行。"
          />
        </label>

        <div className="actions">
          <button
            onClick={() => onRun({ action_type: actionType, action_prompt: actionPrompt, actor_role_id: actorRoleId })}
            disabled={!actionPrompt.trim()}
          >
            执行检定
          </button>
        </div>
      </div>

      <section className="action-result">
        {!lastResult && <p className="hint">暂无结果。</p>}
        {lastResult && (
          <>
            <p>
              结果: {lastResult.success ? '成功' : '失败'} | {lastResult.critical}
            </p>
            <p>
              能力: {lastResult.ability_used}({lastResult.ability_modifier}) | DC: {lastResult.dc} | 掷骰: {lastResult.dice_roll ?? '-'} | 总分: {lastResult.total_score ?? '-'}
            </p>
            <p>耗时: {lastResult.time_spent_min} 分钟</p>
            <p>叙事: {lastResult.narrative}</p>
            {lastResult.applied_effects.length > 0 && <p>影响: {lastResult.applied_effects.join(', ')}</p>}
          </>
        )}
      </section>
    </section>
  );
}
