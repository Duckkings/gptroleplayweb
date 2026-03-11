import { EncounterTimeline } from './EncounterTimeline';
import type { EncounterEntry, NpcRoleCard } from '../types/app';

type Props = {
  encounter: EncounterEntry | null;
  queuedEncounters: EncounterEntry[];
  roleCards?: NpcRoleCard[];
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
  improving: '更稳',
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

export function EncounterLane({ encounter, queuedEncounters, roleCards = [], busy = false, canRejoin = false }: Props) {
  if (!encounter && queuedEncounters.length === 0) return null;

  return (
    <aside className="card encounter-lane">
      <header className="encounter-lane-header">
        <div>
          <h2>并行遭遇</h2>
          <p>{encounter ? `${STATUS_LABEL[encounter.status]} / ${encounter.player_presence === 'away' ? '离场中' : '在场中'}` : '当前没有活跃遭遇'}</p>
        </div>
      </header>

      {encounter ? (
        <>
          <section className="encounter-overview">
            <strong>{encounter.title}</strong>
            <p>{encounter.description}</p>
            <p>
              局势值: {encounter.situation_value}/100
              {encounter.situation_start_value ? ` (起始 ${encounter.situation_start_value})` : ''}
            </p>
            <p>趋势: {TREND_LABEL[encounter.situation_trend]}</p>
            {encounter.scene_summary && <p>当前局势: {encounter.scene_summary}</p>}
            {encounter.latest_outcome_summary && <p>最近进展: {encounter.latest_outcome_summary}</p>}
            {encounter.last_outcome_package?.narrative_summary && <p>结果摘要: {encounter.last_outcome_package.narrative_summary}</p>}
            <p className="hint">遭遇推进请直接在主聊天输入。</p>
            {busy && <p className="hint">遭遇状态同步中...</p>}
            {encounter.player_presence === 'away' && !canRejoin && <p className="hint">回到遭遇发生地后会自动重新接入。</p>}
            {encounter.player_presence === 'away' && canRejoin && <p className="hint">已回到遭遇地点，系统正在尝试重新接入。</p>}
          </section>

          {interactiveNpcNames(encounter, roleCards).length > 0 && (
            <section className="encounter-conditions">
              <h3>遭遇可互动 NPC</h3>
              {interactiveNpcNames(encounter, roleCards).map((name) => (
                <article key={name} className="encounter-condition">
                  <strong>{name}</strong>
                  <p>该角色只在当前遭遇期间参与公开互动，并会直接推动局势变化。</p>
                </article>
              ))}
            </section>
          )}

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
