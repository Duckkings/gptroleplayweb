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
        <p>这里显示按结算卡顺序自动拼接出的公开回合描述。</p>
      </header>

      {narration ? (
        <article className="msg assistant public-turn-narrative-card">
          <strong>GM</strong>
          <p>{narration}</p>
          {status === 'paused' && <p className="hint">当前回合已暂停，等待玩家处理未完成的公开回合事件。</p>}
        </article>
      ) : (
        <article className="msg assistant public-turn-narrative-card pending">
          <strong>GM</strong>
          <p>{status === 'paused' ? '当前回合已暂停。' : '当前还没有可拼接的公开回合叙述。'}</p>
        </article>
      )}
    </section>
  );
}
