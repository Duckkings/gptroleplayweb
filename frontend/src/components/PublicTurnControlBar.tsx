import type { EnvironmentRiskLevel, PublicTurnPhase } from '../types/app';

type Props = {
  phase: PublicTurnPhase;
  roundNumber?: number | null;
  currentActorName?: string | null;
  riskLevel: EnvironmentRiskLevel;
  situationValue?: number | null;
};

const PHASE_LABELS: Record<PublicTurnPhase, string> = {
  idle: '待命',
  initiative_declaration: '先攻声明',
  initiative_execution: '先攻执行',
  normal_advancement: '常规推进',
  gm_push: 'GM 推动',
  situation_advancement: '局势推进',
  awaiting_player_interaction: '等待互动回应',
  awaiting_player_reaction: '等待反应检定',
  awaiting_player_opposed: '等待对抗回应',
  awaiting_player_attack_response: '等待攻击回应',
  awaiting_player_attack_defense: '等待攻击防御',
  awaiting_player_death_save: '等待死亡豁免',
  awaiting_player_information_check: '等待信息检定',
};

const RISK_LABELS: Record<EnvironmentRiskLevel, string> = {
  stable: '稳定',
  risky: '危险',
  collapse: '崩坏',
};

type SummaryPillProps = {
  label: string;
  value: string | number;
  emphasized?: boolean;
};

function SummaryPill({ label, value, emphasized = false }: SummaryPillProps) {
  return (
    <div className={`public-turn-summary-pill ${emphasized ? 'is-emphasized' : ''}`.trim()}>
      <span className="public-turn-summary-pill-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function PublicTurnControlBar({ phase, roundNumber, currentActorName, riskLevel, situationValue }: Props) {
  return (
    <section className="public-turn-summary-strip" aria-label="公开回合状态">
      <div className="public-turn-summary-strip-title">公开回合</div>
      <div className="public-turn-summary-strip-list">
        <SummaryPill label="阶段" value={PHASE_LABELS[phase]} />
        <SummaryPill label="回合" value={typeof roundNumber === 'number' ? roundNumber : '-'} />
        <SummaryPill label="当前行动者" value={currentActorName || '等待玩家'} emphasized />
        <SummaryPill label="环境风险" value={RISK_LABELS[riskLevel]} />
        <SummaryPill label="局势值" value={typeof situationValue === 'number' ? situationValue : '-'} />
      </div>
    </section>
  );
}
