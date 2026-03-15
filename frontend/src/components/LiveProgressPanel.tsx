import type { LiveProgressEntry } from '../types/app';

type LiveProgressPanelProps = {
  entries: LiveProgressEntry[];
  compact?: boolean;
};

export function LiveProgressPanel({ entries, compact = false }: LiveProgressPanelProps) {
  if (entries.length === 0) return null;
  return (
    <section className={`live-progress-panel${compact ? ' compact' : ''}`}>
      <header className="live-progress-header">
        <h3>生成进度</h3>
        <p>正在执行的阶段与工具</p>
      </header>
      <div className="live-progress-list">
        {entries.map((entry) => (
          <article key={entry.id} className={`live-progress-entry ${entry.status}`}>
            <div className="live-progress-meta">
              <strong>{entry.label}</strong>
              <span>{entry.status === 'running' ? '进行中' : entry.status === 'done' ? '已完成' : '失败'}</span>
            </div>
            {entry.detail && <p>{entry.detail}</p>}
          </article>
        ))}
      </div>
    </section>
  );
}
