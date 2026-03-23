import type { EncounterEntry, NpcRoleCard } from '../types/app';

type Props = {
  encounter: EncounterEntry | null;
  roleCards?: NpcRoleCard[];
  busy?: boolean;
  onContinue: () => void;
  onMinimize?: () => void;
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

export function EncounterModal({ encounter, roleCards = [], busy = false, onContinue, onMinimize }: Props) {
  if (!encounter) return null;
  const mainNpcName = resolveMainNpcName(encounter, roleCards);

  return (
    <div className="modal-mask">
      <div className="modal-card modal-wide">
        <div className="modal-header-actions">
          <h3>遭遇事件</h3>
          {onMinimize ? (
            <button type="button" onClick={onMinimize} disabled={busy}>
              暂时关闭
            </button>
          ) : null}
        </div>
        <strong>{encounter.title}</strong>
        <p>{encounter.description}</p>
        {encounter.goal ? <p>遭遇目标: {encounter.goal}</p> : null}
        <p>
          局势值 {encounter.situation_value}/100
          {encounter.situation_start_value ? ` (起始 ${encounter.situation_start_value})` : ''}
        </p>
        <p>趋势: {TREND_LABEL[encounter.situation_trend]}</p>
        {encounter.scene_summary ? <p>当前局势: {encounter.scene_summary}</p> : null}
        {(mainNpcName || encounter.temporary_npcs.length > 0) ? (
          <div>
            <strong>遭遇相关角色</strong>
            {mainNpcName ? <p>{mainNpcName}</p> : null}
            {encounter.temporary_npcs.map((item) => (
              <p key={item.encounter_npc_id}>
                {item.name}
                {item.title ? ` / ${item.title}` : ''}
              </p>
            ))}
          </div>
        ) : null}
        {encounter.last_outcome_package?.narrative_summary ? <p>结果摘要: {encounter.last_outcome_package.narrative_summary}</p> : null}
        <p>关闭后请在主聊天中描述你的动作或发言。</p>
        <div className="actions">
          <button onClick={onContinue} disabled={busy}>
            {busy ? '处理中...' : '继续'}
          </button>
        </div>
      </div>
    </div>
  );
}
