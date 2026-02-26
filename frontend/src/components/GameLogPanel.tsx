import { useEffect, useState } from 'react';
import type { GameLogEntry } from '../types/app';

type Props = {
  open: boolean;
  items: GameLogEntry[];
  aiFetchLimit: number;
  onClose: () => void;
  onSetLimit: (next: number) => void;
};

export function GameLogPanel({ open, items, aiFetchLimit, onClose, onSetLimit }: Props) {
  const [draft, setDraft] = useState(String(aiFetchLimit));

  useEffect(() => {
    setDraft(String(aiFetchLimit));
  }, [aiFetchLimit, open]);

  if (!open) return null;

  return (
    <section className="map-panel card">
      <header className="chat-header">
        <div>
          <h2>游戏日志</h2>
          <p>记录玩家输入和系统反馈。AI 拉取默认条数可配置。</p>
        </div>
        <div className="actions">
          <button onClick={onClose}>关闭日志</button>
        </div>
      </header>

      <div className="actions">
        <label className="zoom-label">
          AI 拉取条数
          <input
            type="number"
            min={1}
            max={100}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            style={{ width: 100 }}
          />
        </label>
        <button onClick={() => onSetLimit(Math.max(1, Math.min(100, Number(draft) || 10)))}>保存</button>
      </div>

      <section className="messages" style={{ maxHeight: '62vh' }}>
        {items.length === 0 && <p className="hint">暂无游戏日志。</p>}
        {items.map((item) => (
          <article key={item.id} className="msg assistant">
            <strong>{item.kind}</strong>
            <p>{item.message}</p>
            <p>{new Date(item.created_at).toLocaleString()}</p>
          </article>
        ))}
      </section>
    </section>
  );
}
