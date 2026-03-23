import type { RefObject } from 'react';

type Props = {
  title: string;
  actionLabel?: string;
  speechLabel?: string;
  actionValue: string;
  speechValue: string;
  actionPlaceholder: string;
  speechPlaceholder: string;
  submitLabel: string;
  busy: boolean;
  disabled?: boolean;
  speechOnly?: boolean;
  showSpeech?: boolean;
  actionInputRef?: RefObject<HTMLTextAreaElement | null>;
  onActionChange: (value: string) => void;
  onSpeechChange: (value: string) => void;
  onSubmit: () => void;
};

export function PublicTurnActionComposer({
  title,
  actionLabel = '行为',
  speechLabel = '语言',
  actionValue,
  speechValue,
  actionPlaceholder,
  speechPlaceholder,
  submitLabel,
  busy,
  disabled = false,
  speechOnly = false,
  showSpeech = true,
  actionInputRef,
  onActionChange,
  onSpeechChange,
  onSubmit,
}: Props) {
  return (
    <section className="composer">
      <h3>{title}</h3>
      <div className="composer-input-grid">
        <div className="composer-input-block">
          <label htmlFor="public-turn-action-input">{actionLabel}</label>
          <textarea
            id="public-turn-action-input"
            ref={actionInputRef}
            value={actionValue}
            onChange={(event) => onActionChange(event.target.value)}
            placeholder={actionPlaceholder}
            disabled={busy || disabled || speechOnly}
          />
        </div>
        {showSpeech && (
          <div className="composer-input-block">
            <label htmlFor="public-turn-speech-input">{speechLabel}</label>
            <textarea
              id="public-turn-speech-input"
              value={speechValue}
              onChange={(event) => onSpeechChange(event.target.value)}
              placeholder={speechPlaceholder}
              disabled={busy || disabled}
            />
          </div>
        )}
      </div>
      {speechOnly && <p className="hint">当前状态下不能进行可影响世界的行为，只能输入语言。</p>}
      <div className="actions">
        <button type="button" disabled={busy || disabled} onClick={onSubmit}>
          {submitLabel}
        </button>
      </div>
    </section>
  );
}
