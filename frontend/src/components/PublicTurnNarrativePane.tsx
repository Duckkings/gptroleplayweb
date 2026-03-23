import type { ReactNode } from 'react';

import { DamageResolutionInlineCard, isDamageResolutionEvent } from './DamageResolutionInlineCard';
import type { PublicTurnPresentation, SceneEvent } from '../types/app';

type Props = {
  presentation: PublicTurnPresentation | null;
  variant?: 'main_output' | 'history';
  sceneEvents?: SceneEvent[];
  inlinePanel?: ReactNode;
};

function cleanText(value: string | null | undefined): string {
  return (value ?? '').trim();
}

function unwrapJsonText(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  const fenceMatch = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  const candidate = (fenceMatch?.[1] ?? trimmed).trim();
  if (!candidate.startsWith('{')) {
    return candidate;
  }
  try {
    const parsed = JSON.parse(candidate) as Record<string, unknown>;
    for (const key of ['outcome', 'outcome_description', 'outcome_narration']) {
      const next = parsed[key];
      if (typeof next === 'string' && next.trim()) {
        return next.trim();
      }
    }
  } catch {
    return trimmed;
  }
  return trimmed;
}

function deriveNarration(presentation: PublicTurnPresentation | null): string {
  const directNarration =
    cleanText(presentation?.accumulated_narration) ||
    cleanText(presentation?.round_narration);
  if (directNarration) {
    return unwrapJsonText(directNarration);
  }
  const summaryLines = (presentation?.settlement_entries ?? [])
    .map((entry) => unwrapJsonText(cleanText(entry.gm_resolution_summary)))
    .filter(Boolean);
  return summaryLines.join('\n');
}

export function PublicTurnNarrativePane({ presentation, variant = 'history', sceneEvents = [], inlinePanel = null }: Props) {
  const narration = deriveNarration(presentation);
  const status = presentation?.narrative_status ?? presentation?.round_narration_status ?? 'empty';
  const damageEvents = sceneEvents.filter((event) => isDamageResolutionEvent(event));

  return (
    <section className={`public-turn-narrative-pane ${variant === 'main_output' ? 'is-main-output' : 'is-history'}`}>
      <header className="public-turn-pane-header">
        <h3>连续叙述</h3>
        <p>这里只保留回合结果摘要；详细行为与对白放在结算卡里。</p>
      </header>

      <article className={`msg assistant public-turn-narrative-card ${narration ? '' : 'pending'}`.trim()}>
        <strong>GM</strong>
        <p>{narration || (status === 'paused' ? '当前回合已暂停，等待玩家处理未完成事件。' : '当前还没有可展示的公开回合摘要。')}</p>
        {status === 'paused' ? <p className="hint">公开回合当前处于暂停状态。</p> : null}
      </article>

      {variant === 'main_output' && inlinePanel ? <div className="public-turn-narrative-inline">{inlinePanel}</div> : null}

      {damageEvents.length > 0 ? (
        <div className="public-turn-damage-list">
          {damageEvents.map((event) => (
            <DamageResolutionInlineCard key={event.event_id} event={event} compact={variant !== 'main_output'} />
          ))}
        </div>
      ) : null}
    </section>
  );
}
