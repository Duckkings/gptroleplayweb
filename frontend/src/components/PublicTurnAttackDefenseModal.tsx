import type { CSSProperties } from 'react';

import type { ActionCheckResult, PublicTurnAttackDefensePrompt } from '../types/app';

type Phase = 'ready' | 'rolling' | 'resolving' | 'resolved' | 'error';

type Rotation = {
  x: number;
  y: number;
  z: number;
};

type Props = {
  open: boolean;
  prompt: PublicTurnAttackDefensePrompt | null;
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

function attackKindLabel(kind: PublicTurnAttackDefensePrompt['attack_kind']): string {
  return kind === 'aoe_attack' ? '范围攻击' : '指定目标攻击';
}

export function PublicTurnAttackDefenseModal({
  open,
  prompt,
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
  const canRoll = phase === 'ready';

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
            <h3>公开回合攻击对抗</h3>
            <p>你的回应已被判定为有效阻碍，现在直接掷出这次攻击对抗的 d20。</p>
          </div>
          {onMinimize ? (
            <button type="button" onClick={onMinimize} disabled={phase === 'rolling' || phase === 'resolving'}>
              暂时关闭
            </button>
          ) : null}
        </div>

        <section className="roll-result-card">
          <p>攻击者: {prompt.source_actor_name}</p>
          <p>防御者: {prompt.target_actor_name}</p>
          <p>攻击分类: {attackKindLabel(prompt.attack_kind)}</p>
          <p>攻击行为: {prompt.source_action_summary}</p>
          {prompt.source_speech_text ? <p>攻击方语言: {prompt.source_speech_text}</p> : null}
          <p>你的回应行为: {prompt.target_action_summary}</p>
          {prompt.target_speech_text ? <p>你的回应语言: {prompt.target_speech_text}</p> : null}
          <div className="scene-event-kv-grid">
            <p>
              攻击方属性: {prompt.source_attack_ability_used} {formatModifier(prompt.source_attack_ability_modifier)}
            </p>
            <p>
              你的防御属性: {prompt.target_defense_ability_used} {formatModifier(prompt.target_defense_ability_modifier)}
            </p>
          </div>
          <p>焦点: {prompt.stakes_summary}</p>
          {prompt.threatened_target_names.length > 0 ? <p>危险目标池: {prompt.threatened_target_names.join('、')}</p> : null}
          {prompt.hit_target_names.length > 0 ? <p>已进入命中池: {prompt.hit_target_names.join('、')}</p> : null}
          {prompt.aoe_remaining_target_count > 0 ? <p>后续待结算目标数: {prompt.aoe_remaining_target_count}</p> : null}
        </section>

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

        {phase === 'ready' ? <p className="roll-modal-caption">点击骰子，结算这次攻击对抗。</p> : null}
        {phase === 'rolling' ? <p className="roll-modal-caption">骰子滚动中...</p> : null}
        {phase === 'resolving' ? <p className="roll-modal-caption">点数已锁定为 {rollValue ?? '?'}，正在比较攻击与防御结果...</p> : null}
        {phase === 'error' ? <p className="error">{errorMessage}</p> : null}

        {phase === 'resolved' && result ? (
          <section className={`roll-result-card ${result.success ? 'is-success' : 'is-failure'}`}>
            <p>
              结果: {result.success ? '你挡住了这次攻击' : '攻击方压过了你的防御'} | {describeCritical(result.critical)}
            </p>
            <div className="scene-event-kv-grid">
              <p>
                你: d20({result.dice_roll ?? rollValue ?? '-'}) {formatModifier(result.ability_modifier)} = {result.total_score ?? '-'}
              </p>
              <p>
                对方: {result.target_name || '攻击方'} d20({result.target_dice_roll ?? '-'}) {formatModifier(result.target_ability_modifier)} ={' '}
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
