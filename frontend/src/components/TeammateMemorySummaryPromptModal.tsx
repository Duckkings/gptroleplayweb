type Props = {
  open: boolean;
  npcName: string;
  busy: boolean;
  onGenerateAndClose: () => void;
  onCloseDirect: () => void;
  onContinue: () => void;
};

export function TeammateMemorySummaryPromptModal({
  open,
  npcName,
  busy,
  onGenerateAndClose,
  onCloseDirect,
  onContinue,
}: Props) {
  if (!open) return null;

  return (
    <div className="modal-mask teammate-memory-summary-mask">
      <div className="modal-card teammate-memory-summary-modal">
        <header className="chat-header">
          <div>
            <h2>生成队友记忆摘要</h2>
            <p>{npcName} 本次单聊有尚未摘要的内容。</p>
          </div>
        </header>
        <section className="teammate-memory-summary-body">
          <p>退出前是否要为这次单聊生成一条记忆摘要？公开回合会优先参考这些摘要，而不是原始聊天记录。</p>
        </section>
        <footer className="actions teammate-memory-summary-actions">
          <button type="button" onClick={onGenerateAndClose} disabled={busy}>
            {busy ? '生成中...' : '生成摘要后关闭'}
          </button>
          <button type="button" onClick={onCloseDirect} disabled={busy}>
            直接关闭
          </button>
          <button type="button" onClick={onContinue} disabled={busy}>
            继续聊天
          </button>
        </footer>
      </div>
    </div>
  );
}
