import type { EncounterStepEntry } from '../types/app';

type Props = {
  steps: EncounterStepEntry[];
};

const STEP_LABELS: Record<EncounterStepEntry['kind'], string> = {
  announcement: '遭遇出现',
  player_action: '你的行动',
  gm_update: '局势推进',
  npc_reaction: 'NPC反应',
  team_reaction: '队友反应',
  temp_npc_action: '遭遇NPC行动',
  escape_attempt: '离场尝试',
  background_tick: '后台推进',
  world_push: '世界推进',
  resolution: '遭遇结束',
};

function metadataText(step: EncounterStepEntry, key: string): string {
  const value = step.metadata?.[key];
  return typeof value === 'string' ? value : '';
}

export function EncounterTimeline({ steps }: Props) {
  return (
    <div className="encounter-timeline">
      {steps.length === 0 && <p className="hint">当前还没有遭遇步骤记录。</p>}
      {steps.map((step) => (
        <article key={step.step_id} className="encounter-step">
          <strong>
            {STEP_LABELS[step.kind]}
            {step.actor_name ? ` / ${step.actor_name}` : ''}
          </strong>
          <p>{step.content}</p>
          {metadataText(step, 'moved_to_label') && <p className="hint">移动到：{metadataText(step, 'moved_to_label')}</p>}
          {metadataText(step, 'impact_summary') && <p className="hint">影响：{metadataText(step, 'impact_summary')}</p>}
          <p className="hint">{step.created_at}</p>
        </article>
      ))}
    </div>
  );
}
