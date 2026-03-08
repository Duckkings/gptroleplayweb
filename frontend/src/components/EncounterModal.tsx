import type { EncounterEntry } from '../types/app';

type Props = {
  encounter: EncounterEntry | null;
  prompt: string;
  busy?: boolean;
  onPromptChange: (value: string) => void;
  onSubmit: (encounterId: string, prompt: string) => void;
};

export function EncounterModal({ encounter, prompt, busy = false, onPromptChange, onSubmit }: Props) {
  if (!encounter) return null;

  return (
    <div className="modal-mask">
      <div className="modal-card modal-wide">
        <h3>遭遇事件</h3>
        <strong>{encounter.title}</strong>
        <p>{encounter.description}</p>
        <textarea
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          placeholder="输入你打算采取的动作..."
          disabled={busy}
        />
        <div className="actions">
          <button onClick={() => onSubmit(encounter.encounter_id, prompt.trim())} disabled={busy || !prompt.trim()}>
            {busy ? '处理中...' : '执行动作'}
          </button>
        </div>
      </div>
    </div>
  );
}
