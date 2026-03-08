import type { EncounterDebugOverviewResponse } from '../types/app';

type Props = {
  overview: EncounterDebugOverviewResponse | null;
};

export function EncounterDebugPanel({ overview }: Props) {
  if (!overview) return null;

  return (
    <section className="card encounter-debug-panel">
      <h3>遭遇调试概览</h3>
      <p>{overview.summary}</p>
      {overview.active_encounter && (
        <p>
          活跃遭遇: {overview.active_encounter.title} / {overview.active_encounter.status} / {overview.active_encounter.player_presence}
        </p>
      )}
      <p>排队遭遇: {overview.queued_encounters.length}</p>
    </section>
  );
}
