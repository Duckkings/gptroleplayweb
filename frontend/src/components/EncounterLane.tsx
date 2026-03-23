import type { AreaSnapshot, EncounterEntry, NpcRoleCard } from '../types/app';

type Props = {
  encounter: EncounterEntry | null;
  queuedEncounters: EncounterEntry[];
  roleCards?: NpcRoleCard[];
  areaSnapshot?: AreaSnapshot | null;
  busy?: boolean;
  collapsed: boolean;
  onToggle: () => void;
};

const STATUS_LABEL: Record<EncounterEntry['status'], string> = {
  queued: '待激活',
  active: '进行中',
  resolved: '已结束',
  expired: '已过期',
  invalidated: '已失效',
};

const TREND_LABEL: Record<EncounterEntry['situation_trend'], string> = {
  improving: '转稳',
  stable: '持平',
  worsening: '恶化',
};

function resolveMainNpcName(encounter: EncounterEntry, roleCards: NpcRoleCard[]): string | null {
  if (!encounter.npc_role_id) return null;
  return roleCards.find((item) => item.role_id === encounter.npc_role_id)?.name ?? encounter.npc_role_id;
}

function interactiveNpcNames(encounter: EncounterEntry, roleCards: NpcRoleCard[]): string[] {
  const names: string[] = [];
  const mainNpc = resolveMainNpcName(encounter, roleCards);
  if (mainNpc) names.push(mainNpc);
  for (const tempNpc of encounter.temporary_npcs ?? []) {
    if (tempNpc.name) names.push(tempNpc.name);
  }
  return names;
}

function locationLabel(encounter: EncounterEntry, areaSnapshot: AreaSnapshot | null | undefined): string {
  if (!encounter.zone_id && !encounter.sub_zone_id) return '未知地点';
  const zoneName =
    areaSnapshot?.zones.find((item) => item.zone_id === encounter.zone_id)?.name ?? encounter.zone_id ?? '未知区域';
  const subZoneName =
    areaSnapshot?.sub_zones.find((item) => item.sub_zone_id === encounter.sub_zone_id)?.name ??
    encounter.sub_zone_id ??
    '未知子区域';
  return `${zoneName} / ${subZoneName}`;
}

export function EncounterLane({
  encounter,
  queuedEncounters,
  roleCards = [],
  areaSnapshot,
  busy = false,
  collapsed,
  onToggle,
}: Props) {
  if (!encounter && queuedEncounters.length === 0) return null;

  const activeCount = encounter ? 1 : 0;
  const totalCount = activeCount + queuedEncounters.length;

  if (collapsed) {
    return (
      <aside className="card encounter-lane is-collapsed">
        <button
          type="button"
          className="encounter-lane-toggle"
          onClick={onToggle}
          aria-expanded="false"
          aria-label="展开并行遭遇"
        >
          <span className="encounter-lane-toggle-label">遭遇</span>
          <strong className="encounter-lane-toggle-count">{totalCount}</strong>
        </button>
        <div className="encounter-lane-collapsed-body">
          {encounter ? (
            <>
              <span className="encounter-lane-chip is-active">{STATUS_LABEL[encounter.status]}</span>
              <strong className="encounter-lane-collapsed-title">{encounter.title}</strong>
              <span className="encounter-lane-collapsed-metric">SV {encounter.situation_value}</span>
            </>
          ) : (
            <>
              <span className="encounter-lane-chip is-queued">排队中</span>
              <strong className="encounter-lane-collapsed-title">{queuedEncounters.length} 个待处理遭遇</strong>
            </>
          )}
        </div>
      </aside>
    );
  }

  return (
    <aside className="card encounter-lane">
      <header className="encounter-lane-header">
        <div>
          <h2>并行遭遇</h2>
          <p>{encounter ? `${STATUS_LABEL[encounter.status]} / 局势 ${encounter.situation_value}/100` : '当前没有活跃遭遇'}</p>
        </div>
        <button type="button" className="encounter-lane-collapse-button" onClick={onToggle} aria-expanded="true">
          收起
        </button>
      </header>

      {encounter ? (
        <>
          <section className="encounter-overview">
            <strong>{encounter.title}</strong>
            <p>{encounter.description}</p>
            {encounter.goal ? <p>遭遇目标: {encounter.goal}</p> : null}
            <p>
              局势值 {encounter.situation_value}/100
              {encounter.situation_start_value ? ` (起始 ${encounter.situation_start_value})` : ''}
            </p>
            <p>趋势: {TREND_LABEL[encounter.situation_trend]}</p>
            <p>当前地点: {locationLabel(encounter, areaSnapshot)}</p>
            {encounter.scene_summary ? <p>当前局势: {encounter.scene_summary}</p> : null}
            {encounter.last_outcome_package?.narrative_summary ? <p>结果摘要: {encounter.last_outcome_package.narrative_summary}</p> : null}
            <p className="hint">遭遇推进请直接在主聊天输入。</p>
            {busy ? <p className="hint">遭遇状态同步中...</p> : null}
          </section>

          {interactiveNpcNames(encounter, roleCards).length > 0 ? (
            <section className="encounter-conditions">
              <h3>遭遇相关角色</h3>
              {interactiveNpcNames(encounter, roleCards).map((name) => (
                <article key={name} className="encounter-condition">
                  <strong>{name}</strong>
                  <p>该角色当前参与这场遭遇，并会影响现场局势。</p>
                </article>
              ))}
            </section>
          ) : null}

          <section className="encounter-conditions">
            <h3>终止条件</h3>
            {encounter.termination_conditions.length === 0 ? <p className="hint">当前未记录终止条件。</p> : null}
            {encounter.termination_conditions.map((condition) => (
              <article key={condition.condition_id} className={`encounter-condition ${condition.satisfied ? 'done' : ''}`}>
                <strong>{condition.satisfied ? '已满足' : '未满足'}</strong>
                <p>{condition.description}</p>
              </article>
            ))}
          </section>

          <section className="encounter-steps">
            <h3>局势摘要</h3>
            <div className="encounter-steps-scroll">
              <p>{encounter.scene_summary || '当前还没有新的局势摘要。'}</p>
            </div>
          </section>
        </>
      ) : (
        <p className="hint">当前没有活跃遭遇。</p>
      )}

      {queuedEncounters.length > 0 ? (
        <section className="encounter-queue">
          <h3>排队遭遇</h3>
          {queuedEncounters.map((item) => (
            <article key={item.encounter_id} className="encounter-queue-item">
              <strong>{item.title}</strong>
              <p>{item.description}</p>
              {item.goal ? <p>目标: {item.goal}</p> : null}
              <p>
                预设局势 {item.situation_value}/100 / {TREND_LABEL[item.situation_trend]}
              </p>
            </article>
          ))}
        </section>
      ) : null}
    </aside>
  );
}
