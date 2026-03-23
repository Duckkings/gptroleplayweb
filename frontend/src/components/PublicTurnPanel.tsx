import type { RefObject } from 'react';

import type { PublicTurnState } from '../types/app';
import { PublicTurnActionComposer } from './PublicTurnActionComposer';

type Props = {
  state: PublicTurnState;
  actionValue: string;
  speechValue: string;
  busy: boolean;
  godMode: boolean;
  actionInputRef?: RefObject<HTMLTextAreaElement | null>;
  onActionChange: (value: string) => void;
  onSpeechChange: (value: string) => void;
  onSubmitGodOverride: () => void;
};

export function PublicTurnPanel({
  state,
  actionValue,
  speechValue,
  busy,
  godMode,
  actionInputRef,
  onActionChange,
  onSpeechChange,
  onSubmitGodOverride,
}: Props) {
  const awaitingPlayerEntry = Boolean(state.awaiting_player_entry && !state.current_round);

  if (!awaitingPlayerEntry || !godMode) {
    return null;
  }

  return (
    <section className="public-turn-godmode-panel">
      <PublicTurnActionComposer
        title="God Mode 注入"
        actionLabel="注入内容"
        speechLabel="补充对白"
        actionValue={actionValue}
        speechValue={speechValue}
        actionPlaceholder="输入一条作为本回合最高优先级玩家行动的自由指令。"
        speechPlaceholder="可选：补充一句会同步进入回合的对白。"
        submitLabel="以上帝模式开始"
        busy={busy}
        actionInputRef={actionInputRef}
        onActionChange={onActionChange}
        onSpeechChange={onSpeechChange}
        onSubmit={onSubmitGodOverride}
      />
    </section>
  );
}
