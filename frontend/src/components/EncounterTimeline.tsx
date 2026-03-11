import type { EncounterStepEntry } from '../types/app';

type Props = {
  steps: EncounterStepEntry[];
  maxItems?: number;
};

const STEP_LABELS: Record<EncounterStepEntry['kind'], string> = {
  announcement: '遭遇出现',
  player_action: '你的行动',
  gm_update: '局势推进',
  npc_reaction: 'NPC反应',
  team_reaction: '队友反应',
  temp_npc_action: '遭遇NPC行动',
  escape_attempt: '逃离尝试',
  background_tick: '后台推进',
  resolution: '遭遇结束',
};

export function EncounterTimeline({ steps, maxItems = 8 }: Props) {
  const items = steps.slice().reverse().slice(0, maxItems).reverse();

  return (
    <div className="encounter-timeline">
      {items.length === 0 && <p className="hint">当前还没有遭遇步骤记录。</p>}
      {items.map((step) => (
        <article key={step.step_id} className="encounter-step">
          <strong>
            {STEP_LABELS[step.kind]}
            {step.actor_name ? ` / ${step.actor_name}` : ''}
          </strong>
          <p>{step.content}</p>
          <p className="hint">{step.created_at}</p>
        </article>
      ))}
    </div>
  );
}
