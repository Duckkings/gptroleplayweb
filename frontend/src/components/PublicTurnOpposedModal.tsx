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
  onTrigger: () => void;
  onClose: () => void;
  onMinimize?: () => void;
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
  onTrigger,
  onClose,
  onMinimize,
}: Props) {
  if (!open || !prompt) return null;

  const dieStyle = {
    '--roll-x': `${rotation.x}deg`,
    '--roll-y': `${rotation.y}deg`,
    '--roll-z': `${rotation.z}deg`,
  } as CSSProperties;
  const canRoll = phase === 'ready' && plan !== null;

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
        <div className="roll-modal-header modal-header-actions">
          <div>
            <h3>公开回合对抗掷骰</h3>
            <p>文本回应已经在主叙述区确认完成，这里只负责结算这次对抗的 d20。</p>
          </div>
          {onMinimize ? (
            <button type="button" onClick={onMinimize} disabled={phase === 'rolling' || phase === 'resolving'}>
              暂时关闭
            </button>
          ) : null}
        </div>

        <section className="roll-result-card">
          <p>发起者: {prompt.source_actor_name}</p>
          <p>目标: {prompt.target_actor_name}</p>
          <p>对方行为: {prompt.source_action_summary}</p>
          {prompt.source_speech_text ? <p>对方语言: {prompt.source_speech_text}</p> : null}
          <p>对抗焦点: {prompt.stakes_summary}</p>
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
            <p>你的动作摘要: {plan.target_action_summary}</p>
            {plan.target_speech_text ? <p>你的语言: {plan.target_speech_text}</p> : null}
          </section>
        ) : null}

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

        {!plan ? <p className="roll-modal-caption">尚未收到对抗规划，请返回主叙述区重新规划。</p> : null}
        {plan && phase === 'ready' ? <p className="roll-modal-caption">点击骰子，结算这次对抗。</p> : null}
        {phase === 'rolling' ? <p className="roll-modal-caption">骰子滚动中...</p> : null}
        {phase === 'resolving' ? <p className="roll-modal-caption">点数已锁定为 {rollValue ?? '?'}，正在比较双方结果...</p> : null}
        {phase === 'error' ? <p className="error">{errorMessage}</p> : null}

        {phase === 'resolved' && result ? (
          <section className={`roll-result-card ${result.success ? 'is-success' : 'is-failure'}`}>
            <p>
              结果: {result.success ? '你顶住了这次对抗' : '对方压过了你的回应'} | {describeCritical(result.critical)}
            </p>
            <div className="scene-event-kv-grid">
              <p>
                你: d20({result.dice_roll ?? rollValue ?? '-'}) {formatModifier(result.ability_modifier)} = {result.total_score ?? '-'}
              </p>
              <p>
                对方: {result.target_name || '对手'} d20({result.target_dice_roll ?? '-'}) {formatModifier(result.target_ability_modifier)} ={' '}
                {result.target_total_score ?? '-'}
              </p>
            </div>
            <p>{result.narrative}</p>
            <p>关闭后继续公开回合。</p>
          </section>
        ) : null}

        {(phase === 'resolved' || phase === 'error') && (
          <div className="actions">
            <button type="button" onClick={onClose}>
              {phase === 'resolved' ? '继续' : '关闭'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
