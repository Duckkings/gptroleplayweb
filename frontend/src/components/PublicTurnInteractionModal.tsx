import type { PublicTurnInteractionPrompt } from '../types/app';

type Props = {
  open: boolean;
  prompt: PublicTurnInteractionPrompt | null;
  actionValue: string;
  speechValue: string;
  busy?: boolean;
  errorMessage?: string;
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
            <h3>公开回合交互</h3>
            <p>先写下你的应对行为，再由系统判断是否升级为对抗。</p>
            {prompt.alternation_depth > 0 ? <p>这是一段已经反向后的交互。</p> : null}
          </div>
          {onMinimize ? (
            <button type="button" onClick={onMinimize} disabled={busy}>
              暂时关闭
            </button>
          ) : null}
        </div>

        <section className="roll-result-card">
          <p>发起者: {prompt.source_actor_name}</p>
          <p>目标: {prompt.target_actor_name}</p>
          <p>对方行为: {prompt.source_action_summary}</p>
          {prompt.source_speech_text ? <p>对方语言: {prompt.source_speech_text}</p> : null}
          {prompt.source_speech_target_name && prompt.source_speech_target_name !== prompt.target_actor_name ? (
            <p>说话对象: {prompt.source_speech_target_name}</p>
          ) : null}
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
                placeholder="你打算如何回应这次互动？"
                disabled={busy}
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
          <p className="roll-modal-caption">只有明确形成互相对抗时，才会进入双方骰点。</p>
        </section>

        {errorMessage ? <p className="error">{errorMessage}</p> : null}

        <div className="actions">
          <button type="button" onClick={onNoAction} disabled={busy}>
            不做任何行动
          </button>
          <button type="button" onClick={onSubmit} disabled={busy || (!actionValue.trim() && !speechValue.trim())}>
            {busy ? '提交中...' : '提交回应'}
          </button>
        </div>
      </div>
    </div>
  );
}
