import type { QuestEntry } from '../types/app';

type Props = {
  quest: QuestEntry | null;
  onClose: () => void;
};

function renderQuestMeta(quest: QuestEntry): string {
  const parts = [quest.source === 'fate' ? '命运任务' : '普通任务', quest.status];
  if (quest.is_tracked) parts.push('当前追踪');
  return parts.join(' | ');
}

export function QuestInspectModal({ quest, onClose }: Props) {
  if (!quest) return null;

  return (
    <div className="modal-mask">
      <div className="modal-card modal-wide">
        <h3>当前任务详情</h3>
        <strong>{quest.title}</strong>
        <p>{renderQuestMeta(quest)}</p>
        <p>{quest.description}</p>
        <div className="quest-detail-meta">
          <p>任务 ID: {quest.quest_id}</p>
          <p>发布区域: {quest.zone_id ?? '未指定'} / {quest.sub_zone_id ?? '未指定'}</p>
          <p>接受时间: {quest.accepted_at ?? '未接受'}</p>
        </div>

        <div className="quest-objective-list">
          {quest.objectives.map((objective) => (
            <div key={objective.objective_id} className="quest-objective-item">
              <span>{objective.title}</span>
              <small>
                {objective.status} {objective.progress_current}/{objective.progress_target}
              </small>
            </div>
          ))}
          {quest.objectives.length === 0 && <p className="hint">当前任务没有目标数据。</p>}
        </div>

        {(quest.rewards ?? []).length > 0 && (
          <div className="quest-reward-list">
            {quest.rewards.map((reward) => (
              <div key={reward.reward_id} className="quest-reward-item">
                <span>{reward.label}</span>
                <small>{reward.kind}</small>
              </div>
            ))}
          </div>
        )}

        <div className="quest-log-list">
          {(quest.logs ?? []).slice().reverse().map((log) => (
            <div key={log.id} className="quest-log-item">
              <span>{log.kind}</span>
              <small>{log.message}</small>
            </div>
          ))}
          {(quest.logs ?? []).length === 0 && <p className="hint">当前没有任务日志。</p>}
        </div>

        <div className="actions">
          <button onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  );
}
