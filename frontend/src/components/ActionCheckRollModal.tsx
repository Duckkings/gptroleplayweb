import type { CSSProperties } from 'react';
import type { ActionCheckResult } from '../types/app';

type Phase = 'ready' | 'rolling' | 'resolving' | 'resolved' | 'error';

type Rotation = {
  x: number;
  y: number;
  z: number;
};

type Props = {
  open: boolean;
  phase: Phase;
  rollValue: number | null;
  result: ActionCheckResult | null;
  errorMessage: string;
  rotation: Rotation;
  onTrigger: () => void;
  onClose: () => void;
};

function describeCritical(critical: ActionCheckResult['critical']): string {
  if (critical === 'critical_success') return '天然20，大成功';
  if (critical === 'critical_failure') return '天然1，大失败';
  return '普通结果';
}

export function ActionCheckRollModal({ open, phase, rollValue, result, errorMessage, rotation, onTrigger, onClose }: Props) {
  if (!open) return null;

  const dieStyle = {
    '--roll-x': `${rotation.x}deg`,
    '--roll-y': `${rotation.y}deg`,
    '--roll-z': `${rotation.z}deg`,
  } as CSSProperties;

  return (
    <div
      className={`roll-modal-mask ${phase === 'ready' ? 'is-clickable' : ''}`}
      onClick={() => {
        if (phase === 'ready') onTrigger();
      }}
      role="presentation"
    >
      <div
        className="roll-modal-card"
        onClick={() => {
          if (phase === 'ready') onTrigger();
        }}
        role="dialog"
        aria-modal="true"
      >
        <div className="roll-modal-header">
          <div>
            <h3>检定投骰</h3>
            <p>锁定中。点击任意空白区域开始掷出 1d20。</p>
          </div>
        </div>

        <div className="roll-modal-stage">
          <div className={`d20-die phase-${phase}`} style={dieStyle}>
            <div className="d20-core" />
            <div className="d20-glow" />
            <span className="d20-value">{phase === 'ready' ? 'd20' : rollValue ?? '?'}</span>
          </div>
        </div>

        {phase === 'ready' && <p className="roll-modal-caption">点击遮罩或卡片外区域开始投骰。</p>}
        {phase === 'rolling' && <p className="roll-modal-caption">骰子滚动中...</p>}
        {phase === 'resolving' && <p className="roll-modal-caption">点数已锁定为 {rollValue ?? '?'}，正在请求检定结果...</p>}
        {phase === 'error' && <p className="error">{errorMessage}</p>}

        {phase === 'resolved' && result && (
          <section className={`roll-result-card ${result.success ? 'is-success' : 'is-failure'}`}>
            <p>
              结果: {result.success ? '成功' : '失败'} | {describeCritical(result.critical)}
            </p>
            {result.requires_check ? (
              <p>
                d20({result.dice_roll ?? rollValue ?? '-'}) + 修正 {result.ability_modifier} = {result.total_score ?? '-'}，对抗 DC {result.dc}
              </p>
            ) : (
              <p>本次行动无需正式检定，系统直接判定为成功。</p>
            )}
            <p>能力: {result.ability_used}</p>
            <p className="hint">叙事结果将在关闭后显示到聊天区。</p>
          </section>
        )}

        <div className="actions">
          {(phase === 'resolved' || phase === 'error') && (
            <button
              onClick={(event) => {
                event.stopPropagation();
                onClose();
              }}
            >
              {phase === 'resolved' ? '继续' : '关闭'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
