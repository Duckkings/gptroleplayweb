import type { BattleStepEntry } from '../types/app';

type Props = {
  steps: BattleStepEntry[];
};

export function BattleLogPanel({ steps }: Props) {
  return (
    <section className="battle-panel battle-log-panel">
      <h4>战斗日志</h4>
      <div className="battle-log-scroll">
        {steps.length === 0 && <p className="hint">暂无战斗日志。</p>}
        {steps.map((step) => (
          <article key={step.step_id} className="battle-log-entry">
            <p>
              <strong>R{step.round}</strong> {step.actor_name ? `${step.actor_name} / ` : ''}
              {step.content}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
