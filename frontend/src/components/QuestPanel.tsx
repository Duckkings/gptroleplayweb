import type { QuestEntry, QuestState } from '../types/app';

type Props = {
  state: QuestState;
  onTrackQuest?: (questId: string) => void;
  onEvaluateQuest?: (questId: string) => void;
};

function renderQuestMeta(quest: QuestEntry): string {
  const parts = [quest.source === 'fate' ? '命运任务' : '普通任务', quest.status];
  if (quest.is_tracked) parts.push('当前追踪');
  return parts.join(' | ');
}

export function QuestPanel({ state, onTrackQuest, onEvaluateQuest }: Props) {
  const quests = state.quests ?? [];

  return (
    <section className="quest-panel-block">
      <header className="quest-panel-header">
        <div>
          <h3>任务列表</h3>
          <p>显示当前玩家拥有的任务、目标进度和任务日志。</p>
        </div>
      </header>

      {quests.length === 0 && <p className="hint">当前没有任务。</p>}
      <div className="quest-list">
        {quests.map((quest) => (
          <article key={quest.quest_id} className={`quest-card ${quest.is_tracked ? 'tracked' : ''}`}>
            <strong>{quest.title}</strong>
            <p>{renderQuestMeta(quest)}</p>
            <p>{quest.description}</p>
            <div className="quest-objective-list">
              {quest.objectives.map((objective) => (
                <div key={objective.objective_id} className="quest-objective-item">
                  <span>{objective.title}</span>
                  <small>
                    {objective.status} {objective.progress_current}/{objective.progress_target}
                  </small>
                </div>
              ))}
            </div>
            <div className="actions">
              {quest.status === 'active' && !quest.is_tracked && onTrackQuest && (
                <button onClick={() => onTrackQuest(quest.quest_id)}>设为当前任务</button>
              )}
              {quest.status === 'active' && onEvaluateQuest && <button onClick={() => onEvaluateQuest(quest.quest_id)}>检查完成</button>}
            </div>
            <div className="quest-log-list">
              {(quest.logs ?? []).slice(-5).map((log) => (
                <div key={log.id} className="quest-log-item">
                  <span>{log.kind}</span>
                  <small>{log.message}</small>
                </div>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
