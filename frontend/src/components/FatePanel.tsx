import type { FateState } from '../types/app';

type Props = {
  open: boolean;
  state: FateState;
  onClose: () => void;
};

export function FatePanel({ open, state, onClose }: Props) {
  if (!open) return null;

  return (
    <section className="map-panel card">
      <header className="chat-header">
        <div>
          <h2>命运信息</h2>
          <p>查看当前命运线、阶段状态与历史归档。</p>
        </div>
        <button onClick={onClose}>关闭</button>
      </header>

      {!state.current_fate && <p className="hint">当前还没有命运线。</p>}
      {state.current_fate && (
        <div className="fate-panel-block">
          <article className="fate-card">
            <strong>{state.current_fate.title}</strong>
            <p>{state.current_fate.summary}</p>
            <p>状态：{state.current_fate.status}</p>
            <div className="fate-phase-list">
              {state.current_fate.phases.map((phase) => (
                <div key={phase.phase_id} className="fate-phase-item">
                  <span>
                    阶段 {phase.index} - {phase.title}
                  </span>
                  <small>{phase.status}</small>
                  <p>{phase.description}</p>
                </div>
              ))}
            </div>
          </article>
        </div>
      )}

      {state.archive.length > 0 && (
        <section className="fate-panel-block">
          <h3>归档命运线</h3>
          <div className="fate-phase-list">
            {state.archive.map((item) => (
              <div key={item.fate_id} className="fate-phase-item">
                <span>{item.title}</span>
                <small>{item.status}</small>
              </div>
            ))}
          </div>
        </section>
      )}
    </section>
  );
}
