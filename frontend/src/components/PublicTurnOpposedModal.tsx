import type { CSSProperties } from 'react';
import type { ActionCheckResult, PublicTurnOpposedPlanResponse, PublicTurnOpposedPrompt } from '../types/app';

type Phase = 'ready' | 'rolling' | 'resolving' | 'resolved' | 'error';

type Rotation = {
  x: number;
  y: number;
  z: number;
};

type Props = {
  open: boolean;
  prompt: PublicTurnOpposedPrompt | null;
  plan: PublicTurnOpposedPlanResponse | null;
  phase: Phase;
  rollValue: number | null;
  result: ActionCheckResult | null;
  errorMessage: string;
  rotation: Rotation;
  actionValue: string;
  speechValue: string;
  onActionChange: (value: string) => void;
  onSpeechChange: (value: string) => void;
  onPlan: () => void;
  onTrigger: () => void;
  onClose: () => void;
};

function formatModifier(value: number | null | undefined): string {
  const safeValue = typeof value === 'number' ? value : 0;
  return safeValue >= 0 ? `+${safeValue}` : `${safeValue}`;
}

function describeCritical(critical: ActionCheckResult['critical']): string {
  if (critical === 'critical_success') return 'Natural 20';
  if (critical === 'critical_failure') return 'Natural 1';
  return 'Normal';
}

export function PublicTurnOpposedModal({
  open,
  prompt,
  plan,
  phase,
  rollValue,
  result,
  errorMessage,
  rotation,
  actionValue,
  speechValue,
  onActionChange,
  onSpeechChange,
  onPlan,
  onTrigger,
  onClose,
}: Props) {
  if (!open || !prompt) return null;

  const dieStyle = {
    '--roll-x': `${rotation.x}deg`,
    '--roll-y': `${rotation.y}deg`,
    '--roll-z': `${rotation.z}deg`,
  } as CSSProperties;
  const canPlan = phase !== 'rolling' && phase !== 'resolving' && phase !== 'resolved';
  const canRoll = phase === 'ready' && plan !== null;
  const planning = phase === 'resolving' && !result && !plan;

  return (
    <div className="roll-modal-mask" role="presentation">
      <div
        className="roll-modal-card"
        onClick={(event) => {
          event.stopPropagation();
        }}
        role="dialog"
        aria-modal="true"
      >
        <div className="roll-modal-header">
          <div>
            <h3>公开回合对抗</h3>
            <p>先确认对方动作与自己的回应，再投出这次对抗的 d20。</p>
          </div>
        </div>

        <section className="roll-result-card">
          <p>发起者: {prompt.source_actor_name}</p>
          <p>目标: {prompt.target_actor_name}</p>
          <p>对方行为: {prompt.source_action_summary}</p>
          {prompt.source_speech_text ? <p>对方语言: {prompt.source_speech_text}</p> : null}
          <p>风险: {prompt.stakes_summary}</p>
        </section>

        <section className="chat-interactions">
          <h3>你的回应</h3>
          <div className="composer-input-grid">
            <div className="composer-input-block">
              <label htmlFor="public-turn-opposed-action">行为</label>
              <textarea
                id="public-turn-opposed-action"
                rows={4}
                value={actionValue}
                onChange={(event) => onActionChange(event.target.value)}
                placeholder="你准备如何对抗这次动作？"
                disabled={!canPlan}
              />
            </div>
            <div className="composer-input-block">
              <label htmlFor="public-turn-opposed-speech">语言</label>
              <textarea
                id="public-turn-opposed-speech"
                rows={4}
                value={speechValue}
                onChange={(event) => onSpeechChange(event.target.value)}
                placeholder="可选：你在对抗时说了什么？"
                disabled={!canPlan}
              />
            </div>
          </div>
          <div className="actions">
            {phase !== 'resolved' ? (
              <button type="button" onClick={onPlan} disabled={!canPlan}>
                {plan ? '重新规划对抗' : '规划对抗'}
              </button>
            ) : null}
          </div>
        </section>

        {plan ? (
          <section className="roll-result-card">
            <p>对抗任务: {plan.check_task}</p>
            <div className="scene-event-kv-grid">
              <p>
                对方属性: {plan.source_ability_used} {formatModifier(plan.source_ability_modifier)}
              </p>
              <p>
                你的属性: {plan.target_ability_used} {formatModifier(plan.target_ability_modifier)}
              </p>
            </div>
            <p>对方动作摘要: {plan.source_action_summary}</p>
            <p>你的动作摘要: {plan.target_action_summary}</p>
            {plan.target_speech_text ? <p>你的语言: {plan.target_speech_text}</p> : null}
          </section>
        ) : null}

        {plan ? (
          <div className="roll-modal-stage">
            <button
              type="button"
              className={`d20-die phase-${phase}`}
              style={dieStyle}
              onClick={() => {
                if (canRoll) onTrigger();
              }}
              disabled={!canRoll}
            >
              <div className="d20-core" />
              <div className="d20-glow" />
              <span className="d20-value">{phase === 'ready' ? 'd20' : rollValue ?? '?'}</span>
            </button>
          </div>
        ) : null}

        {!plan && !planning ? <p className="roll-modal-caption">先规划对抗，再开始掷骰。</p> : null}
        {planning ? <p className="roll-modal-caption">正在规划这次对抗...</p> : null}
        {phase === 'rolling' ? <p className="roll-modal-caption">骰子滚动中...</p> : null}
        {phase === 'resolving' && plan ? <p className="roll-modal-caption">点数已锁定为 {rollValue ?? '?'}，正在比较双方结果...</p> : null}
        {phase === 'error' ? <p className="error">{errorMessage}</p> : null}

        {phase === 'resolved' && result ? (
          <section className={`roll-result-card ${result.success ? 'is-success' : 'is-failure'}`}>
            <p>
              结果: {result.success ? '你顶住了这次对抗' : '对方压过了你的回应'} | {describeCritical(result.critical)}
            </p>
            <div className="scene-event-kv-grid">
              <p>
                对方: d20({result.dice_roll ?? '-'}) {formatModifier(result.ability_modifier)} = {result.total_score ?? '-'}
              </p>
              <p>
                你: d20({result.target_dice_roll ?? rollValue ?? '-'}) {formatModifier(result.target_ability_modifier)} ={' '}
                {result.target_total_score ?? '-'}
              </p>
            </div>
            <p>{result.narrative}</p>
            <p>关闭后继续公开回合。</p>
          </section>
        ) : null}

        <div className="actions">
          {phase === 'resolved' || phase === 'error' ? (
            <button type="button" onClick={onClose}>
              {phase === 'resolved' ? '继续' : '关闭'}
            </button>
          ) : (
            <button type="button" onClick={onClose}>
              取消
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
