import type { QuestEntry } from '../types/app';

type Props = {
  quest: QuestEntry | null;
  busy?: boolean;
  onAccept: (questId: string) => void;
  onReject: (questId: string) => void;
};

export function QuestModal({ quest, busy = false, onAccept, onReject }: Props) {
  if (!quest) return null;

  return (
    <div className="modal-mask">
      <div className="modal-card modal-wide">
        <h3>{quest.source === 'fate' ? '命运任务' : '新任务'}</h3>
        <strong>{quest.title}</strong>
        <p>{quest.description}</p>
        <div className="quest-objective-list">
          {quest.objectives.map((objective) => (
            <div key={objective.objective_id} className="quest-objective-item">
              <span>{objective.title}</span>
              <small>{objective.description}</small>
            </div>
          ))}
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
        <div className="actions">
          <button onClick={() => onAccept(quest.quest_id)} disabled={busy}>
            接受
          </button>
          {quest.offer_mode === 'accept_reject' && (
            <button onClick={() => onReject(quest.quest_id)} disabled={busy}>
              拒绝
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
