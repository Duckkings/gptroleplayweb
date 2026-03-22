import type { CSSProperties } from 'react';

import type { DeathSavePrompt } from '../types/app';

type Phase = 'ready' | 'rolling' | 'resolving' | 'resolved' | 'error';

type Rotation = {
  x: number;
  y: number;
  z: number;
};

type Props = {
  open: boolean;
  prompt: DeathSavePrompt | null;
  phase: Phase;
  rollValue: number | null;
  summaryText: string;
  errorMessage: string;
  rotation: Rotation;
  onTrigger: () => void;
  onClose: () => void;
  onMinimize?: () => void;
};

export function PublicTurnDeathSaveModal({
  open,
  prompt,
  phase,
  rollValue,
  summaryText,
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
            <h3>死亡豁免</h3>
            <p>你当前只能说话，随后必须进行一次死亡豁免掷骰。</p>
          </div>
          {onMinimize ? (
            <button type="button" onClick={onMinimize} disabled={phase === 'rolling' || phase === 'resolving'}>
              暂时关闭
            </button>
          ) : null}
        </div>

        <section className="roll-result-card">
          <p>角色: {prompt.actor_name}</p>
          <p>
            当前进度: 成功 {prompt.successes}/3, 失败 {prompt.failures}/3
          </p>
          <p>判定 DC: {prompt.dc}</p>
          <p>重伤阈值: 单次再受伤达到 {prompt.severe_wound_threshold} HP 将直接死亡</p>
        </section>

        <div className="roll-modal-stage">
          <button
            type="button"
            className={`d20-die phase-${phase}`}
            style={dieStyle}
            onClick={() => {
              if (phase === 'ready') onTrigger();
            }}
            disabled={phase !== 'ready'}
          >
            <div className="d20-core" />
            <div className="d20-glow" />
            <span className="d20-value">{phase === 'ready' ? 'd20' : rollValue ?? '?'}</span>
          </button>
        </div>

        {phase === 'ready' ? <p className="roll-modal-caption">点击骰子，进行这次死亡豁免。</p> : null}
        {phase === 'rolling' ? <p className="roll-modal-caption">骰子滚动中...</p> : null}
        {phase === 'resolving' ? <p className="roll-modal-caption">点数已锁定为 {rollValue ?? '?'}，正在结算死亡豁免...</p> : null}
        {phase === 'error' ? <p className="error">{errorMessage}</p> : null}

        {phase === 'resolved' && summaryText ? (
          <section className="roll-result-card">
            <p>{summaryText}</p>
            <p>关闭后继续公开回合。</p>
          </section>
        ) : null}

        {(phase === 'resolved' || phase === 'error') && (
          <div className="actions">
            <button type="button" onClick={onClose}>
              {phase === 'resolved' ? '继续' : '重试'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
