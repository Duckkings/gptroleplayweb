import type { EncounterEntry } from '../types/app';

type Props = {
  encounter: EncounterEntry | null;
  busy?: boolean;
  onContinue: () => void;
};

const TREND_LABEL: Record<EncounterEntry['situation_trend'], string> = {
  improving: '上升',
  stable: '稳定',
  worsening: '恶化',
};

export function EncounterModal({ encounter, busy = false, onContinue }: Props) {
  if (!encounter) return null;

  return (
    <div className="modal-mask">
      <div className="modal-card modal-wide">
        <h3>遭遇事件</h3>
        <strong>{encounter.title}</strong>
        <p>{encounter.description}</p>
        <p>
          局势值: {encounter.situation_value}/100
          {encounter.situation_start_value ? `（起始 ${encounter.situation_start_value}）` : ''}
        </p>
        <p>趋势: {TREND_LABEL[encounter.situation_trend]}</p>
        {encounter.scene_summary && <p>当前局势: {encounter.scene_summary}</p>}
        {encounter.last_outcome_package?.narrative_summary && <p>上次结果: {encounter.last_outcome_package.narrative_summary}</p>}
        <p>关闭后请在主聊天中描述你的动作或发言。</p>
        <div className="actions">
          <button onClick={onContinue} disabled={busy}>
            {busy ? '处理中...' : '继续'}
          </button>
        </div>
      </div>
    </div>
  );
}
