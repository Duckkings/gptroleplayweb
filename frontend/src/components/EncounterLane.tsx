import { EncounterTimeline } from './EncounterTimeline';
import type { EncounterEntry } from '../types/app';

type Props = {
  encounter: EncounterEntry | null;
  queuedEncounters: EncounterEntry[];
  prompt: string;
  busy?: boolean;
  readOnly?: boolean;
  canRejoin?: boolean;
  onPromptChange: (value: string) => void;
  onSubmitAction: (encounterId: string, prompt: string) => void;
  onEscape: (encounterId: string) => void;
  onRejoin: (encounterId: string) => void;
};

const STATUS_LABEL: Record<EncounterEntry['status'], string> = {
  queued: '待激活',
  active: '进行中',
  resolved: '已结束',
  escaped: '已脱离',
  expired: '已过期',
  invalidated: '已失效',
};

export function EncounterLane({
  encounter,
  queuedEncounters,
  prompt,
  busy = false,
  readOnly = false,
  canRejoin = false,
  onPromptChange,
  onSubmitAction,
  onEscape,
  onRejoin,
}: Props) {
  if (!encounter && queuedEncounters.length === 0) return null;

  const actionable = encounter && encounter.status === 'active' && encounter.player_presence === 'engaged';
  const rejoinable = encounter && encounter.player_presence === 'away' && encounter.status !== 'resolved' && canRejoin;

  return (
    <aside className="card encounter-lane">
      <header className="encounter-lane-header">
        <div>
          <h2>并行遭遇</h2>
          <p>{encounter ? `${STATUS_LABEL[encounter.status]} / ${encounter.player_presence === 'away' ? '已离场' : '在场中'}` : '当前没有活跃遭遇'}</p>
        </div>
      </header>

      {encounter ? (
        <>
          <section className="encounter-overview">
            <strong>{encounter.title}</strong>
            <p>{encounter.description}</p>
            {encounter.scene_summary && <p>当前局势：{encounter.scene_summary}</p>}
            {encounter.latest_outcome_summary && <p>最近进展：{encounter.latest_outcome_summary}</p>}
          </section>

          <section className="encounter-conditions">
            <h3>终止条件</h3>
            {encounter.termination_conditions.length === 0 && <p className="hint">当前未记录终止条件。</p>}
            {encounter.termination_conditions.map((condition) => (
              <article key={condition.condition_id} className={`encounter-condition ${condition.satisfied ? 'done' : ''}`}>
                <strong>{condition.satisfied ? '已满足' : '未满足'}</strong>
                <p>{condition.description}</p>
              </article>
            ))}
          </section>

          <section className="encounter-actions">
            <h3>遭遇行动</h3>
            <textarea
              value={prompt}
              onChange={(e) => onPromptChange(e.target.value)}
              placeholder={actionable ? '描述你接下来在遭遇中的行动...' : '当前遭遇暂不可直接推进。'}
              disabled={busy || readOnly || !actionable}
            />
            <div className="actions">
              <button onClick={() => encounter && onSubmitAction(encounter.encounter_id, prompt.trim())} disabled={busy || readOnly || !actionable || !prompt.trim()}>
                {busy ? '处理中...' : '执行动作'}
              </button>
              <button onClick={() => encounter && onEscape(encounter.encounter_id)} disabled={busy || readOnly || !actionable}>
                尝试逃离
              </button>
              <button onClick={() => encounter && onRejoin(encounter.encounter_id)} disabled={busy || readOnly || !rejoinable}>
                重返遭遇
              </button>
            </div>
            {!actionable && encounter.player_presence === 'away' && !canRejoin && <p className="hint">回到遭遇发生地点后，才能重新介入。</p>}
          </section>

          <section className="encounter-steps">
            <h3>最近步骤</h3>
            <EncounterTimeline steps={encounter.steps ?? []} />
          </section>
        </>
      ) : (
        <p className="hint">当前没有活跃遭遇。</p>
      )}

      {queuedEncounters.length > 0 && (
        <section className="encounter-queue">
          <h3>待排队遭遇</h3>
          {queuedEncounters.map((item) => (
            <article key={item.encounter_id} className="encounter-queue-item">
              <strong>{item.title}</strong>
              <p>{item.description}</p>
            </article>
          ))}
        </section>
      )}
    </aside>
  );
}
