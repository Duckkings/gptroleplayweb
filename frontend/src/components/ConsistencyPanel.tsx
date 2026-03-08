import type { ConsistencyIssue, GlobalStorySnapshot, WorldState } from '../types/app';

type Props = {
  open: boolean;
  busy?: boolean;
  worldState: WorldState;
  snapshot: GlobalStorySnapshot | null;
  issueCount: number;
  issues: ConsistencyIssue[];
  onRefresh: () => void;
  onRunCheck: () => void;
  onClose: () => void;
};

export function ConsistencyPanel({
  open,
  busy = false,
  worldState,
  snapshot,
  issueCount,
  issues,
  onRefresh,
  onRunCheck,
  onClose,
}: Props) {
  if (!open) return null;

  return (
    <section className="map-panel card consistency-panel">
      <header className="chat-header">
        <div>
          <h2>一致性状态</h2>
          <p>查看当前世界版本、统一故事快照，以及已检测到的失效引用。</p>
        </div>
        <div className="actions">
          <button onClick={onRefresh} disabled={busy}>
            刷新
          </button>
          <button onClick={onRunCheck} disabled={busy}>
            {busy ? '执行中...' : '执行一致性校验'}
          </button>
          <button onClick={onClose}>关闭</button>
        </div>
      </header>

      <div className="consistency-grid">
        <section className="consistency-block">
          <h3>版本</h3>
          <p>world_revision: {worldState.world_revision}</p>
          <p>map_revision: {worldState.map_revision}</p>
          <p>最近校验: {worldState.last_consistency_check_at ?? '无'}</p>
          <p>最近世界重建: {worldState.last_world_rebuild_at ?? '无'}</p>
          <p>问题数: {issueCount}</p>
        </section>

        <section className="consistency-block">
          <h3>当前快照</h3>
          {!snapshot && <p className="hint">暂无故事快照。</p>}
          {snapshot && (
            <>
              <p>
                区域: {snapshot.current_zone_name || snapshot.current_zone_id || '无'} /{' '}
                {snapshot.current_sub_zone_name || snapshot.current_sub_zone_id || '无'}
              </p>
              <p>
                命运线: {snapshot.current_fate_id ?? '无'} | 当前阶段: {snapshot.current_fate_phase_id ?? '无'}
              </p>
              <p>可用 NPC: {snapshot.available_npc_ids.join(', ') || '无'}</p>
              <p>队伍成员: {snapshot.team_member_ids.join(', ') || '无'}</p>
              <p>活动任务: {snapshot.active_quest_ids.join(', ') || '无'}</p>
              <p>待确认任务: {snapshot.pending_quest_ids.join(', ') || '无'}</p>
              <p>最近遭遇: {snapshot.recent_encounter_ids.join(', ') || '无'}</p>
            </>
          )}
        </section>

        <section className="consistency-block">
          <h3>可见 NPC</h3>
          {!snapshot || snapshot.available_npcs.length === 0 ? (
            <p className="hint">当前没有可见 NPC。</p>
          ) : (
            <div className="consistency-list">
              {snapshot.available_npcs.map((npc) => (
                <article key={npc.role_id} className="consistency-item">
                  <strong>{npc.name}</strong>
                  <p>ID: {npc.role_id}</p>
                  <p>
                    区域: {npc.zone_id ?? '无'} / {npc.sub_zone_id ?? '无'}
                  </p>
                  <p>与玩家关系: {npc.relation_tag ?? '未知'}</p>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="consistency-block">
          <h3>问题列表</h3>
          {issues.length === 0 && <p className="hint">当前未发现一致性问题。</p>}
          {issues.length > 0 && (
            <div className="consistency-list">
              {issues.map((issue) => (
                <article key={issue.issue_id} className={`consistency-item severity-${issue.severity}`}>
                  <strong>
                    [{issue.severity}] {issue.issue_type}
                  </strong>
                  <p>
                    {issue.entity_type}/{issue.entity_id}
                  </p>
                  <p>{issue.message}</p>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
