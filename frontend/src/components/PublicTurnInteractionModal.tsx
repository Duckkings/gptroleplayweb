import type { PublicTurnInteractionPrompt } from '../types/app';

type Props = {
  open: boolean;
  prompt: PublicTurnInteractionPrompt | null;
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

export function PublicTurnInteractionModal({
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
            <h3>公开回合互动</h3>
            <p>先输入你的回应，系统会按当前状态决定是否进入后续结算。</p>
            {prompt.alternation_depth > 0 ? <p>这是已经往返过一次的互动。</p> : null}
          </div>
          {onMinimize ? (
            <button type="button" onClick={onMinimize} disabled={busy}>
              暂时关闭
            </button>
          ) : null}
        </div>

        <section className="roll-result-card">
          <p>发起者: {prompt.source_actor_name}</p>
          <p>需要回应者: {prompt.target_actor_name}</p>
          {prompt.source_action_target_name ? <p>动作对象: {prompt.source_action_target_name}</p> : null}
          <p>对方行为: {prompt.source_action_summary}</p>
          {prompt.source_speech_text ? <p>对方语言: {prompt.source_speech_text}</p> : null}
          {prompt.source_speech_target_name ? <p>说话对象: {prompt.source_speech_target_name}</p> : null}
        </section>

        <section className="chat-interactions">
          <h3>你的回应</h3>
          <div className="composer-input-grid">
            <div className="composer-input-block">
              <label htmlFor="public-turn-interaction-action">行为</label>
              <textarea
                id="public-turn-interaction-action"
                rows={4}
                value={actionValue}
                onChange={(event) => onActionChange(event.target.value)}
                placeholder="描述你如何回应这次互动。"
                disabled={busy || speechOnly}
              />
            </div>
            <div className="composer-input-block">
              <label htmlFor="public-turn-interaction-speech">语言</label>
              <textarea
                id="public-turn-interaction-speech"
                rows={4}
                value={speechValue}
                onChange={(event) => onSpeechChange(event.target.value)}
                placeholder="可选：你当场说了什么？"
                disabled={busy}
              />
            </div>
          </div>
          <p className="roll-modal-caption">
            {speechOnly ? '当前状态下不能输入世界影响行为，只能输入语言。' : '只有明确形成相互对抗时，才会进入双方检定。'}
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
