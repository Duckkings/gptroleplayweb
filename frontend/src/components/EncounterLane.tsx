import { EncounterTimeline } from './EncounterTimeline';
import type { EncounterEntry } from '../types/app';

type Props = {
  encounter: EncounterEntry | null;
  queuedEncounters: EncounterEntry[];
  busy?: boolean;
  canRejoin?: boolean;
};

const STATUS_LABEL: Record<EncounterEntry['status'], string> = {
  queued: '待激活',
  active: '进行中',
  resolved: '已结束',
  escaped: '已脱离',
  expired: '已过期',
  invalidated: '已失效',
};

const TREND_LABEL: Record<EncounterEntry['situation_trend'], string> = {
  improving: '上升',
  stable: '稳定',
  worsening: '恶化',
};

export function EncounterLane({ encounter, queuedEncounters, busy = false, canRejoin = false }: Props) {
  if (!encounter && queuedEncounters.length === 0) return null;

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
            <p>
              局势值: {encounter.situation_value}/100
              {encounter.situation_start_value ? `（起始 ${encounter.situation_start_value}）` : ''}
            </p>
            <p>趋势: {TREND_LABEL[encounter.situation_trend]}</p>
            {encounter.scene_summary && <p>当前局势: {encounter.scene_summary}</p>}
            {encounter.latest_outcome_summary && <p>最近进展: {encounter.latest_outcome_summary}</p>}
            {encounter.last_outcome_package?.narrative_summary && <p>结果摘要: {encounter.last_outcome_package.narrative_summary}</p>}
            <p className="hint">遭遇推进请直接在主聊天输入。</p>
            {busy && <p className="hint">遭遇状态同步中...</p>}
            {encounter.player_presence === 'away' && !canRejoin && <p className="hint">返回遭遇发生地后会自动重新接入。</p>}
            {encounter.player_presence === 'away' && canRejoin && <p className="hint">已回到遭遇地点，系统正在尝试自动重新接入。</p>}
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
          <h3>排队遭遇</h3>
          {queuedEncounters.map((item) => (
            <article key={item.encounter_id} className="encounter-queue-item">
              <strong>{item.title}</strong>
              <p>{item.description}</p>
              <p>
                预设局势: {item.situation_value}/100 / {TREND_LABEL[item.situation_trend]}
              </p>
            </article>
          ))}
        </section>
      )}
    </aside>
  );
}
