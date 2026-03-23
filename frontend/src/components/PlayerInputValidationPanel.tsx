import { useEffect, useState } from 'react';
import type { NpcRoleCard, PlayerInputValidationResponse } from '../types/app';

type Props = {
  open: boolean;
  npcs: NpcRoleCard[];
  playerRoleId: string;
  lastResult: PlayerInputValidationResponse | null;
  busy?: boolean;
  onRun: (payload: { actor_role_id?: string; action_text: string; speech_text: string }) => void;
  onContinueActionCheck: (payload: { actor_role_id?: string; action_prompt: string }) => void;
  onClose: () => void;
};

function renderTextBlock(label: string, value: string) {
  return (
    <div className="validation-text-block">
      <strong>{label}</strong>
      <p>{value.trim() || '无'}</p>
    </div>
  );
}

export function PlayerInputValidationPanel({
  open,
  npcs,
  playerRoleId,
  lastResult,
  busy = false,
  onRun,
  onContinueActionCheck,
  onClose,
}: Props) {
  const [actorRoleId, setActorRoleId] = useState(playerRoleId);
  const [actionText, setActionText] = useState('');
  const [speechText, setSpeechText] = useState('');

  useEffect(() => {
    setActorRoleId(playerRoleId);
  }, [playerRoleId]);

  if (!open) return null;

  const canContinueActionCheck = Boolean(lastResult?.normalized_action_text.trim());

  return (
    <section className="action-panel card validation-panel">
      <header className="chat-header">
        <div>
          <h2>玩家输入校验测试</h2>
          <p>先运行玩家输入校验，确认规范化结果、资源判断和建议文本。</p>
        </div>
        <button onClick={onClose} disabled={busy}>
          关闭
        </button>
      </header>

      <div className="action-form">
        <label>
          执行者
          <select value={actorRoleId} onChange={(event) => setActorRoleId(event.target.value)} disabled={busy}>
            <option value={playerRoleId}>玩家 ({playerRoleId})</option>
            {npcs.map((npc) => (
              <option key={npc.role_id} value={npc.role_id}>
                {npc.name} ({npc.role_id})
              </option>
            ))}
          </select>
        </label>

        <label>
          行为
          <textarea
            value={actionText}
            onChange={(event) => setActionText(event.target.value)}
            placeholder="例如：我冲上去劈砍，再顺手把桌子踹翻。"
            disabled={busy}
          />
        </label>

        <label>
          语言
          <textarea
            value={speechText}
            onChange={(event) => setSpeechText(event.target.value)}
            placeholder="例如：退后。"
            disabled={busy}
          />
        </label>

        <div className="actions">
          <button
            onClick={() =>
              onRun({
                actor_role_id: actorRoleId,
                action_text: actionText.trim(),
                speech_text: speechText.trim(),
              })
            }
            disabled={busy || !actionText.trim() && !speechText.trim()}
          >
            {busy ? '校验中...' : '运行校验'}
          </button>
          <button
            onClick={() =>
              onContinueActionCheck({
                actor_role_id: lastResult?.actor_role_id,
                action_prompt: lastResult?.normalized_action_text ?? '',
              })
            }
            disabled={busy || !canContinueActionCheck}
          >
            继续做行为检定
          </button>
        </div>
      </div>

      <section className="action-result validation-result">
        {!lastResult && <p className="hint">暂无最近一次校验结果。</p>}
        {lastResult && (
          <>
            <div className="validation-grid">
              {renderTextBlock('状态', lastResult.status)}
              {renderTextBlock('执行者', `${lastResult.actor_name} (${lastResult.actor_kind})`)}
            </div>
            <div className="validation-grid">
              {renderTextBlock('规范化行为', lastResult.normalized_action_text)}
              {renderTextBlock('规范化语言', lastResult.normalized_speech_text)}
            </div>
            <div className="validation-grid">
              {renderTextBlock('建议行为', lastResult.fallback_action_text)}
              {renderTextBlock('展示文本', lastResult.display_text)}
            </div>
            <div className="validation-grid">
              {renderTextBlock('资源状态', lastResult.resource_status.check_status)}
              {renderTextBlock('资源类型', lastResult.resource_status.resource_kind)}
            </div>
            {lastResult.resource_status.requirement_summary || lastResult.resource_status.current_summary ? (
              <div className="validation-grid">
                {renderTextBlock('资源需求', lastResult.resource_status.requirement_summary)}
                {renderTextBlock('资源现状', lastResult.resource_status.current_summary)}
              </div>
            ) : null}
            <div className="validation-panel-block">
              <h4>问题列表</h4>
              {lastResult.issues.length === 0 ? (
                <p className="hint">没有问题。</p>
              ) : (
                <ul className="validation-issue-list">
                  {lastResult.issues.map((issue) => (
                    <li key={issue.code}>
                      <strong>{issue.code}</strong>
                      <span>{issue.message}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
      </section>
    </section>
  );
}
