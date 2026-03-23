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
  onMinimize?: () => void;
};

function describeCritical(critical: ActionCheckResult['critical']): string {
  if (critical === 'critical_success') return '自然 20，大成功';
  if (critical === 'critical_failure') return '自然 1，大失败';
  return '普通结果';
}

function formatModifier(value: number | null | undefined): string {
  const safeValue = typeof value === 'number' ? value : 0;
  return safeValue >= 0 ? `+${safeValue}` : `${safeValue}`;
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
  onMinimize,
}: Props) {
  if (!open) return null;

  const dieStyle = {
    '--roll-x': `${rotation.x}deg`,
    '--roll-y': `${rotation.y}deg`,
    '--roll-z': `${rotation.z}deg`,
  } as CSSProperties;

  const planSourceLabel = sourceLabel ?? plan?.source_label ?? undefined;
  const planThreatenedConsequence = threatenedConsequence ?? plan?.threatened_consequence ?? undefined;
  const isOpposed = (plan?.resolution_rule ?? result?.resolution_rule ?? 'static_dc') === 'opposed_actor';

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
        <div className="roll-modal-header modal-header-actions">
          <div>
            <h3>{title ?? '检定掷骰'}</h3>
            <p>{subtitle ?? '点击下方骰子，掷出本次 d20。'}</p>
          </div>
          {onMinimize ? (
            <button type="button" onClick={onMinimize} disabled={phase === 'rolling' || phase === 'resolving'}>
              暂时关闭
            </button>
          ) : null}
        </div>

        {plan ? (
          <section className="roll-result-card">
            {planSourceLabel ? <p>来源: {planSourceLabel}</p> : null}
            <p>执行者: {plan.actor_name}</p>
            <p>检定目标: {plan.check_task || '判断当前行动是否顺利完成'}</p>
            {planThreatenedConsequence ? <p>风险: {planThreatenedConsequence}</p> : null}
            <p>
              属性: {plan.ability_used} | 修正值: {formatModifier(plan.ability_modifier)}
            </p>
            {isOpposed ? (
              <p>
                对抗目标: {plan.target_name || '未知目标'} | 对方修正: {formatModifier(plan.target_ability_modifier)}
              </p>
            ) : (
              <p>DC: {plan.dc}</p>
            )}
            {successHint ? <p>成功后果: {successHint}</p> : null}
            {failureHint ? <p>失败后果: {failureHint}</p> : null}
          </section>
        ) : null}

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

        {phase === 'ready' ? <p className="roll-modal-caption">点击骰子开始检定。</p> : null}
        {phase === 'rolling' ? <p className="roll-modal-caption">骰子滚动中...</p> : null}
        {phase === 'resolving' ? <p className="roll-modal-caption">点数已锁定为 {rollValue ?? '?'}，正在结算...</p> : null}
        {phase === 'error' ? <p className="error">{errorMessage}</p> : null}

        {phase === 'resolved' && result ? (
          <section className={`roll-result-card ${result.success ? 'is-success' : 'is-failure'}`}>
            <p>
              结果: {result.success ? '成功' : '失败'} | {describeCritical(result.critical)}
            </p>
            {result.requires_check ? (
              isOpposed ? (
                <div className="scene-event-kv-grid">
                  <p>
                    我方: d20({result.dice_roll ?? rollValue ?? '-'}) {formatModifier(result.ability_modifier)} = {result.total_score ?? '-'}
                  </p>
                  <p>
                    对方: {result.target_name || '目标'} d20({result.target_dice_roll ?? '-'}) {formatModifier(result.target_ability_modifier)} ={' '}
                    {result.target_total_score ?? '-'}
                  </p>
                </div>
              ) : (
                <p>
                  d20({result.dice_roll ?? rollValue ?? '-'}) {formatModifier(result.ability_modifier)} = {result.total_score ?? '-'}，对抗 DC{' '}
                  {result.dc}
                </p>
              )
            ) : (
              <p>本次行动无需正式检定，系统已按常理直接推进。</p>
            )}
            <p>关闭后会继续本轮结算。</p>
          </section>
        ) : null}

        <div className="actions">
          {phase === 'resolved' || phase === 'error' ? (
            <button onClick={onClose}>{phase === 'resolved' ? '继续' : '关闭'}</button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
