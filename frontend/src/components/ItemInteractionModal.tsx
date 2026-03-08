type Props = {
  open: boolean;
  title: string;
  mode: 'inspect' | 'use';
  prompt: string;
  busy?: boolean;
  lastReply?: string;
  onPromptChange: (value: string) => void;
  onSubmit: () => void;
  onClose: () => void;
};

export function ItemInteractionModal({
  open,
  title,
  mode,
  prompt,
  busy = false,
  lastReply = '',
  onPromptChange,
  onSubmit,
  onClose,
}: Props) {
  if (!open) return null;

  return (
    <div className="modal-mask">
      <div className="modal-card modal-medium">
        <h3>{mode === 'inspect' ? '观察物品' : '使用物品'}</h3>
        <p>{title}</p>
        <textarea
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          placeholder={mode === 'inspect' ? '你想重点观察什么？可留空。' : '你打算如何使用它？'}
          disabled={busy}
        />
        {lastReply && (
          <div className="inventory-interaction-result">
            <strong>最近结果</strong>
            <p>{lastReply}</p>
          </div>
        )}
        <div className="actions">
          <button onClick={onClose} disabled={busy}>
            关闭
          </button>
          <button onClick={onSubmit} disabled={busy || (mode === 'use' && !prompt.trim())}>
            {busy ? '处理中...' : mode === 'inspect' ? '开始观察' : '执行使用'}
          </button>
        </div>
      </div>
    </div>
  );
}
