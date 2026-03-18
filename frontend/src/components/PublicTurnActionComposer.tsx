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
  showSpeech?: boolean;
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
  showSpeech = true,
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
            value={actionValue}
            onChange={(event) => onActionChange(event.target.value)}
            placeholder={actionPlaceholder}
            disabled={busy || disabled}
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
      <div className="actions">
        <button type="button" disabled={busy || disabled} onClick={onSubmit}>
          {submitLabel}
        </button>
      </div>
    </section>
  );
}
