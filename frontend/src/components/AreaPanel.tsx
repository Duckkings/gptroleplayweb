import { useMemo, useState } from 'react';
import type { AreaSnapshot } from '../types/app';

type Props = {
  open: boolean;
  snapshot: AreaSnapshot | null;
  loading: boolean;
  onClose: () => void;
  onInitClock: () => void;
  onRefresh: () => void;
  onMoveSubZone: (subZoneId: string) => void;
  onDiscover: (subZoneId: string, intent: string) => void;
  onExecute: (interactionId: string) => void;
};

function formatClock(snapshot: AreaSnapshot | null): string {
  const c = snapshot?.clock;
  if (!c) return '未初始化';
  const mm = String(c.minute).padStart(2, '0');
  return `${c.year}年${c.month}月${c.day}日 ${c.hour}:${mm}`;
}

export function AreaPanel({
  open,
  snapshot,
  loading,
  onClose,
  onInitClock,
  onRefresh,
  onMoveSubZone,
  onDiscover,
  onExecute,
}: Props) {
  const [intent, setIntent] = useState('观察周围细节');

  const currentSubZone = useMemo(() => {
    if (!snapshot?.current_sub_zone_id) return null;
    return snapshot.sub_zones.find((s) => s.sub_zone_id === snapshot.current_sub_zone_id) ?? null;
  }, [snapshot]);

  if (!open) return null;

  return (
    <section className="area-panel card">
      <header className="chat-header">
        <div>
          <h2>区块面板</h2>
          <p>当前时间: {formatClock(snapshot)}</p>
          <p>当前子区块: {currentSubZone?.name ?? '未选择'}</p>
        </div>
        <div className="actions">
          <button onClick={onInitClock}>初始化时钟</button>
          <button onClick={onRefresh}>刷新</button>
          <button onClick={onClose}>关闭</button>
        </div>
      </header>

      {loading && <p className="hint">处理中...</p>}

      <div className="area-layout">
        <aside className="area-subzones">
          <h3>子区块</h3>
          <div className="zone-name-list">
            {(snapshot?.sub_zones ?? []).map((sub) => (
              <button key={sub.sub_zone_id} className="zone-name-item" onClick={() => onMoveSubZone(sub.sub_zone_id)}>
                {sub.name}
              </button>
            ))}
          </div>
        </aside>

        <section className="area-interactions">
          <h3>交互</h3>
          <div className="actions">
            <input value={intent} onChange={(e) => setIntent(e.target.value)} placeholder="输入发现意图" />
            <button
              onClick={() => {
                if (!currentSubZone) return;
                onDiscover(currentSubZone.sub_zone_id, intent.trim());
              }}
              disabled={!currentSubZone || !intent.trim()}
            >
              发现新交互
            </button>
          </div>

          <div className="area-interaction-list">
            {(currentSubZone?.key_interactions ?? []).map((it) => (
              <article key={it.interaction_id} className="debug-entry">
                <strong>{it.name}</strong>
                <p>
                  {it.type} | {it.generated_mode} | {it.status}
                </p>
                <div className="actions">
                  <button onClick={() => onExecute(it.interaction_id)}>执行（占位）</button>
                </div>
              </article>
            ))}
            {(currentSubZone?.key_interactions?.length ?? 0) === 0 && <p className="hint">当前子区块暂无交互。</p>}
          </div>
        </section>
      </div>
    </section>
  );
}
