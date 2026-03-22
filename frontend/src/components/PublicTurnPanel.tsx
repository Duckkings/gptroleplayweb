import type { PublicTurnState, RoleActionStatus } from '../types/app';
import { PublicTurnActionComposer } from './PublicTurnActionComposer';
import { PublicTurnControlBar } from './PublicTurnControlBar';

type Props = {
  state: PublicTurnState;
  currentActorName?: string | null;
  currentSituationValue?: number | null;
  actionValue: string;
  speechValue: string;
  busy: boolean;
  godMode: boolean;
  playerActionStatus: RoleActionStatus;
  onActionChange: (value: string) => void;
  onSpeechChange: (value: string) => void;
  onStartNextRound: () => void;
  onStartInitiative: () => void;
  onSubmitAction: () => void;
  onSubmitGodOverride: () => void;
};

export function PublicTurnPanel({
  state,
  currentActorName,
  currentSituationValue,
  actionValue,
  speechValue,
  busy,
  godMode,
  playerActionStatus,
  onActionChange,
  onSpeechChange,
  onStartNextRound,
  onStartInitiative,
  onSubmitAction,
  onSubmitGodOverride,
}: Props) {
  const currentRound = state.current_round ?? null;
  const phase = currentRound?.phase ?? 'idle';
  const awaitingPlayerAction = Boolean(currentRound?.awaiting_player_action);
  const awaitingPlayerEntry = Boolean(state.awaiting_player_entry && !currentRound);
  const speechOnly = playerActionStatus === 'death_saving' || playerActionStatus === 'unable_to_act';

  return (
    <>
      <PublicTurnControlBar
        phase={phase}
        roundNumber={currentRound?.round_number ?? null}
        currentActorName={currentActorName}
        riskLevel={currentRound?.environment_risk_level ?? state.environment_risk_level}
        situationValue={currentSituationValue}
        awaitingPlayerEntry={awaitingPlayerEntry}
        godMode={godMode}
        busy={busy}
        onStartNextRound={onStartNextRound}
        onStartInitiative={onStartInitiative}
      />

      {awaitingPlayerAction && (
        <PublicTurnActionComposer
          title={playerActionStatus === 'death_saving' ? '提交语言并进入死亡豁免' : '提交本阶段行动'}
          actionValue={actionValue}
          speechValue={speechValue}
          actionPlaceholder={speechOnly ? '当前状态下不能输入可影响世界的行为。' : '例如：我快步抢到前排，用盾牌压住缺口。'}
          speechPlaceholder={playerActionStatus === 'death_saving' ? '例如：我咬牙说：“我还没倒下。”' : '例如：先稳住阵线，别让局势继续失控。'}
          submitLabel={playerActionStatus === 'death_saving' ? '提交语言并掷死亡豁免' : '提交行动'}
          busy={busy}
          speechOnly={speechOnly}
          onActionChange={onActionChange}
          onSpeechChange={onSpeechChange}
          onSubmit={onSubmitAction}
        />
      )}

      {awaitingPlayerEntry && godMode && (
        <PublicTurnActionComposer
          title="God Mode 注入"
          actionLabel="注入内容"
          speechLabel="补充对白"
          actionValue={actionValue}
          speechValue={speechValue}
          actionPlaceholder="输入一条将作为本回合最高优先级玩家行动的自由指令。"
          speechPlaceholder="可选：补充一句会同步进入回合的对白。"
          submitLabel="以上帝模式开始"
          busy={busy}
          onActionChange={onActionChange}
          onSpeechChange={onSpeechChange}
          onSubmit={onSubmitGodOverride}
        />
      )}

      {!awaitingPlayerEntry && !awaitingPlayerAction && (
        <section className="chat-interactions">
          <p className="hint">当前阶段不接受玩家输入，请等待本轮推进或弹窗处理。</p>
        </section>
      )}
    </>
  );
}
