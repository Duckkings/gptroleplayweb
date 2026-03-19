import type { PublicTurnPresentation } from '../types/app';

type Props = {
  presentation: PublicTurnPresentation | null;
};

export function PublicTurnNarrativePane({ presentation }: Props) {
  const narration = presentation?.accumulated_narration?.trim() || presentation?.round_narration?.trim() || '';
  const status = presentation?.narrative_status ?? presentation?.round_narration_status ?? 'empty';

  return (
    <section className="public-turn-narrative-pane">
      <header className="public-turn-pane-header">
        <h3>连续叙述</h3>
        <p>每个小回合结算后立即追加，不混入检定数值和系统提示。</p>
      </header>

      {narration ? (
        <article className="msg assistant public-turn-narrative-card">
          <strong>GM</strong>
          <p>{narration}</p>
          {status === 'paused' && <p className="hint">叙述暂停，等待下一步行动或对抗。</p>}
        </article>
      ) : status === 'streaming' ? (
        <article className="msg assistant public-turn-narrative-card pending">
          <strong>GM</strong>
          <p>当前片段正在生成中……</p>
        </article>
      ) : (
        <article className="msg assistant public-turn-narrative-card pending">
          <strong>GM</strong>
          <p>本轮叙述会在每个小回合结算后依次追加。</p>
        </article>
      )}
    </section>
  );
}
