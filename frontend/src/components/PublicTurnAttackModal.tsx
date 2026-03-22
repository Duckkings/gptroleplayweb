import type { PublicTurnAttackPrompt } from '../types/app';

type Props = {
  open: boolean;
  prompt: PublicTurnAttackPrompt | null;
  actionValue: string;
  speechValue: string;
  busy?: boolean;
  errorMessage?: string;
  speechOnly?: boolean;
  onActionChange: (value: string) => void;
  onSpeechChange: (value: string) => void;
  onSubmit: () => void;
  onNoAction: () => void;
  onMinimize?: () => void;
};

function attackKindLabel(kind: PublicTurnAttackPrompt['attack_kind']): string {
  return kind === 'aoe_attack' ? '范围攻击' : '指定目标攻击';
}

function attackBasisLabel(basis: PublicTurnAttackPrompt['attack_basis']): string {
  if (basis === 'spell') return '法术';
  if (basis === 'weapon') return '武器';
  return '其他';
}

function areaSummary(prompt: PublicTurnAttackPrompt): string | null {
  if (prompt.attack_kind !== 'aoe_attack') return null;
  if (prompt.attack_area_shape === 'sphere' || prompt.attack_area_shape === 'burst' || prompt.attack_area_shape === 'emanation') {
    return `${prompt.attack_area_shape} / 半径 ${prompt.attack_area_radius_m} 米`;
  }
  if (prompt.attack_area_shape === 'cone' || prompt.attack_area_shape === 'line') {
    return `${prompt.attack_area_shape} / 长度 ${prompt.attack_area_length_m} 米`;
  }
  return prompt.attack_area_shape;
}

export function PublicTurnAttackModal({
  open,
  prompt,
  actionValue,
  speechValue,
  busy = false,
  errorMessage = '',
  speechOnly = false,
  onActionChange,
  onSpeechChange,
  onSubmit,
  onNoAction,
  onMinimize,
}: Props) {
  if (!open || !prompt) return null;

  const rangeText = areaSummary(prompt);

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
            <h3>公开回合攻击回应</h3>
            <p>先输入你如何处理这次攻击，系统会根据当前状态决定是否进入攻击对抗。</p>
          </div>
          {onMinimize ? (
            <button type="button" onClick={onMinimize} disabled={busy}>
              暂时关闭
            </button>
          ) : null}
        </div>

        <section className="roll-result-card">
          <p>发起者: {prompt.source_actor_name}</p>
          <p>当前目标: {prompt.current_target_name}</p>
          <p>
            攻击分类: {attackKindLabel(prompt.attack_kind)} / {attackBasisLabel(prompt.attack_basis)}
          </p>
          {prompt.attack_definition_name ? <p>攻击定义: {prompt.attack_definition_name}</p> : null}
          <p>攻击行为: {prompt.source_action_summary}</p>
          {prompt.source_speech_text ? <p>攻击方语言: {prompt.source_speech_text}</p> : null}
          {rangeText ? <p>范围说明: {rangeText}</p> : null}
          <p>危险目标: {prompt.threatened_target_names.join('、') || '无'}</p>
          {prompt.revealed_target_names.length > 0 ? <p>本次显形目标: {prompt.revealed_target_names.join('、')}</p> : null}
          {prompt.can_include_self ? <p>这次攻击可能波及施术者自身。</p> : null}
          {prompt.player_in_danger ? <p>你处于本次攻击影响范围内。</p> : null}
          {prompt.suggested_response_hint ? <p>回应提示: {prompt.suggested_response_hint}</p> : null}
        </section>

        <section className="chat-interactions">
          <h3>你的处理</h3>
          <div className="composer-input-grid">
            <div className="composer-input-block">
              <label htmlFor="public-turn-attack-action">行为</label>
              <textarea
                id="public-turn-attack-action"
                rows={4}
                value={actionValue}
                onChange={(event) => onActionChange(event.target.value)}
                placeholder="你准备如何处理这次攻击？"
                disabled={busy || speechOnly}
              />
            </div>
            <div className="composer-input-block">
              <label htmlFor="public-turn-attack-speech">语言</label>
              <textarea
                id="public-turn-attack-speech"
                rows={4}
                value={speechValue}
                onChange={(event) => onSpeechChange(event.target.value)}
                placeholder="可选：你当场说了什么？"
                disabled={busy}
              />
            </div>
          </div>
          <p className="roll-modal-caption">
            {speechOnly ? '当前状态下不能输入世界影响行为，只能输入语言。' : '只有能实质阻碍这次攻击的世界性行为，才会进入攻击对抗掷骰。'}
          </p>
        </section>

        {errorMessage ? <p className="error">{errorMessage}</p> : null}

        <div className="actions">
          <button type="button" onClick={onNoAction} disabled={busy}>
            不做任何行动
          </button>
          <button type="button" onClick={onSubmit} disabled={busy || (!speechOnly && !actionValue.trim() && !speechValue.trim())}>
            {busy ? '提交中...' : '提交回应'}
          </button>
        </div>
      </div>
    </div>
  );
}
