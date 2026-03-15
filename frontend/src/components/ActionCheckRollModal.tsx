import type { CSSProperties } from 'react';
import type { ActionCheckPlan, ActionCheckResult } from '../types/app';

type Phase = 'ready' | 'rolling' | 'resolving' | 'resolved' | 'error';

type Rotation = {
  x: number;
  y: number;
  z: number;
};

type Props = {
  open: boolean;
  phase: Phase;
  plan: ActionCheckPlan | null;
  rollValue: number | null;
  result: ActionCheckResult | null;
  errorMessage: string;
  rotation: Rotation;
  title?: string;
  subtitle?: string;
  sourceLabel?: string;
  threatenedConsequence?: string;
  successHint?: string;
  failureHint?: string;
  onTrigger: () => void;
  onClose: () => void;
};

function describeCritical(critical: ActionCheckResult['critical']): string {
  if (critical === 'critical_success') return '天然 20，大成功';
  if (critical === 'critical_failure') return '天然 1，大失败';
  return '普通结果';
}

export function ActionCheckRollModal({
  open,
  phase,
  plan,
  rollValue,
  result,
  errorMessage,
  rotation,
  title,
  subtitle,
  sourceLabel,
  threatenedConsequence,
  successHint,
  failureHint,
  onTrigger,
  onClose,
}: Props) {
  if (!open) return null;
  const planModifierText = plan ? (plan.ability_modifier >= 0 ? `+${plan.ability_modifier}` : `${plan.ability_modifier}`) : '';

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
        onClick={(event) => {
          event.stopPropagation();
        }}
        role="dialog"
        aria-modal="true"
      >
        <div className="roll-modal-header">
          <div>
            <h3>{title ?? '检定掷骰'}</h3>
            <p>{subtitle ?? '点击下方骰子开始掷出本轮 d20。'}</p>
          </div>
        </div>

        {plan && (
          <section className="roll-result-card">
            {sourceLabel && <p>来源：{sourceLabel}</p>}
            <p>执行者：{plan.actor_name}</p>
            <p>检定目标：{plan.check_task || '当前行动是否顺利完成'}</p>
            {threatenedConsequence && <p>威胁：{threatenedConsequence}</p>}
            <p>
              属性：{plan.ability_used} | 调整值：{planModifierText}
            </p>
            <p>DC：{plan.dc}</p>
            {successHint && <p>成功后果：{successHint}</p>}
            {failureHint && <p>失败后果：{failureHint}</p>}
          </section>
        )}

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

        {phase === 'ready' && <p className="roll-modal-caption">点击骰子开始检定。</p>}
        {phase === 'rolling' && <p className="roll-modal-caption">骰子滚动中...</p>}
        {phase === 'resolving' && <p className="roll-modal-caption">点数已锁定为 {rollValue ?? '?'}，正在结算...</p>}
        {phase === 'error' && <p className="error">{errorMessage}</p>}

        {phase === 'resolved' && result && (
          <section className={`roll-result-card ${result.success ? 'is-success' : 'is-failure'}`}>
            <p>
              结果：{result.success ? '成功' : '失败'} | {describeCritical(result.critical)}
            </p>
            {result.requires_check ? (
              <p>
                d20({result.dice_roll ?? rollValue ?? '-'}) {result.ability_modifier >= 0 ? `+${result.ability_modifier}` : result.ability_modifier} ={' '}
                {result.total_score ?? '-'}，对抗 DC {result.dc}
              </p>
            ) : (
              <p>本次行动无需正式检定，系统按常理直接推进。</p>
            )}
            <p>关闭后会继续本轮聊天或系统结算。</p>
          </section>
        )}

        <div className="actions">
          {(phase === 'resolved' || phase === 'error') && <button onClick={onClose}>{phase === 'resolved' ? '继续' : '关闭'}</button>}
        </div>
      </div>
    </div>
  );
}
