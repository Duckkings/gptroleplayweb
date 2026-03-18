import type { EnvironmentRiskLevel, PublicTurnPhase } from '../types/app';

type Props = {
  phase: PublicTurnPhase;
  roundNumber?: number | null;
  currentActorName?: string | null;
  riskLevel: EnvironmentRiskLevel;
  situationValue?: number | null;
  awaitingPlayerEntry: boolean;
  godMode: boolean;
  busy: boolean;
  onStartNextRound: () => void;
  onStartInitiative: () => void;
};

const PHASE_LABELS: Record<PublicTurnPhase, string> = {
  idle: '待机',
  initiative_declaration: '抢先声明',
  initiative_execution: '抢先执行',
  normal_advancement: '常规推进',
  situation_advancement: '事态推进',
  awaiting_player_reaction: '等待反应检定',
};

const RISK_LABELS: Record<EnvironmentRiskLevel, string> = {
  stable: '稳定',
  risky: '危险',
  collapse: '崩塌',
};

export function PublicTurnControlBar({
  phase,
  roundNumber,
  currentActorName,
  riskLevel,
  situationValue,
  awaitingPlayerEntry,
  godMode,
  busy,
  onStartNextRound,
  onStartInitiative,
}: Props) {
  return (
    <section className="chat-interactions">
      <h3>公开回合</h3>
      <div className="scene-event-kv-grid">
        <p>阶段: {PHASE_LABELS[phase]}</p>
        <p>回合: {typeof roundNumber === 'number' ? roundNumber : '-'}</p>
        <p>当前行动者: {currentActorName || '等待玩家'}</p>
        <p>环境风险: {RISK_LABELS[riskLevel]}</p>
        <p>局势值: {typeof situationValue === 'number' ? situationValue : '-'}</p>
      </div>
      {awaitingPlayerEntry && (
        <div className="actions">
          <button type="button" disabled={busy} onClick={onStartNextRound}>
            开始下一回合
          </button>
          <button type="button" disabled={busy} onClick={onStartInitiative}>
            优先行动
          </button>
          {godMode && <span className="hint">God Mode 可在下方直接注入一条自由行动。</span>}
        </div>
      )}
    </section>
  );
}
