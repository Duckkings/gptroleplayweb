import type { NpcRoleCard } from '../types/app';

type Props = {
  open: boolean;
  items: NpcRoleCard[];
  total: number;
  search: string;
  selected: NpcRoleCard | null;
  onSearch: (next: string) => void;
  onRefresh: () => void;
  onSelect: (roleId: string) => void;
  onClose: () => void;
};

export function NpcPoolPanel({
  open,
  items,
  total,
  search,
  selected,
  onSearch,
  onRefresh,
  onSelect,
  onClose,
}: Props) {
  if (!open) return null;

  return (
    <section className="npc-pool-panel card">
      <header className="chat-header">
        <div>
          <h2>NPC 角色池</h2>
          <p>总数 {total}，可按名称或ID搜索</p>
        </div>
        <div className="actions">
          <button onClick={onRefresh}>刷新</button>
          <button onClick={onClose}>关闭</button>
        </div>
      </header>

      <div className="npc-pool-layout">
        <section className="npc-pool-list-block">
          <input
            type="text"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder="搜索 NPC 名称 / ID"
          />
          <div className="npc-pool-list">
            {items.length === 0 && <p className="hint">暂无 NPC。</p>}
            {items.map((npc) => (
              <button key={npc.role_id} className="npc-item" onClick={() => onSelect(npc.role_id)}>
                <strong>{npc.name}</strong>
                <small>{npc.role_id}</small>
              </button>
            ))}
          </div>
        </section>

        <section className="npc-pool-detail">
          {!selected && <p className="hint">点击左侧 NPC 查看角色卡。</p>}
          {selected && (
            <>
              <h3>{selected.name}</h3>
              <p>ID: {selected.role_id}</p>
              <p>区域: {selected.zone_id ?? '-'} / 子区: {selected.sub_zone_id ?? '-'}</p>
              <p>状态: {selected.state}</p>
              <p>性格: {selected.personality || '-'}</p>
              <p>说话方式: {selected.speaking_style || '-'}</p>
              <p>外观: {selected.appearance || '-'}</p>
              <p>背景: {selected.background || '-'}</p>
              <p>认知: {selected.cognition || '-'}</p>
              <p>阵营: {selected.alignment || '-'}</p>
              <p>等级: {selected.profile.dnd5e_sheet.level}</p>
              <p>
                HP: {selected.profile.dnd5e_sheet.hit_points.current}/{selected.profile.dnd5e_sheet.hit_points.maximum}
              </p>
              <p>
                STR/DEX/CON/INT/WIS/CHA: {selected.profile.dnd5e_sheet.ability_scores.strength}/
                {selected.profile.dnd5e_sheet.ability_scores.dexterity}/
                {selected.profile.dnd5e_sheet.ability_scores.constitution}/
                {selected.profile.dnd5e_sheet.ability_scores.intelligence}/
                {selected.profile.dnd5e_sheet.ability_scores.wisdom}/
                {selected.profile.dnd5e_sheet.ability_scores.charisma}
              </p>
              <div>
                <strong>预生成关系</strong>
                {selected.relations.length === 0 && <p className="hint">暂无关系。</p>}
                {selected.relations.map((r, idx) => (
                  <p key={`${r.target_role_id}_${idx}`}>
                    {r.target_role_id} | {r.relation_tag} | {r.note || '-'}
                  </p>
                ))}
              </div>
              <div>
                <strong>聊天记录（最新20条）</strong>
                {(selected.dialogue_logs ?? []).length === 0 && <p className="hint">暂无聊天记录。</p>}
                {(selected.dialogue_logs ?? []).slice(-20).map((log) => (
                  <p key={log.id}>
                    [{log.world_time_text}] {log.speaker_name}: {log.content}
                  </p>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </section>
  );
}
