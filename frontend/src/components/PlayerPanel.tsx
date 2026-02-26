import { useEffect, useState } from 'react';
import type { PlayerStaticData } from '../types/app';

type Props = {
  open: boolean;
  value: PlayerStaticData;
  onClose: () => void;
  onSave: (next: PlayerStaticData) => void;
};

export function PlayerPanel({ open, value, onClose, onSave }: Props) {
  const [draft, setDraft] = useState<PlayerStaticData>(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  if (!open) return null;

  return (
    <section className="player-panel card">
      <header className="chat-header">
        <div>
          <h2>玩家数据面板</h2>
          <p>可编辑静态数据（姓名、移动速度）</p>
        </div>
        <button onClick={onClose}>关闭</button>
      </header>

      <div className="player-form">
        <label>
          玩家ID
          <input
            type="text"
            value={draft.player_id}
            onChange={(e) => setDraft((prev) => ({ ...prev, player_id: e.target.value }))}
          />
        </label>
        <label>
          玩家名称
          <input
            type="text"
            value={draft.name}
            onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
          />
        </label>
        <label>
          移动速度(m/h)
          <input
            type="number"
            min={1}
            value={draft.move_speed_mph}
            onChange={(e) => setDraft((prev) => ({ ...prev, move_speed_mph: Number(e.target.value) || 1 }))}
          />
        </label>
      </div>

      <div className="actions">
        <button onClick={() => onSave(draft)}>保存玩家数据</button>
      </div>
    </section>
  );
}
