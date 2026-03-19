import { useEffect, useState } from 'react';

import type { BattleStartRequest } from '../types/app';

type Props = {
  open: boolean;
  minimized?: boolean;
  busy?: boolean;
  currentZoneName: string;
  currentSubZoneName: string;
  subZoneDescription: string;
  dangerScore?: number | null;
  reputationScore?: number | null;
  onClose: () => void;
  onConfirm: (payload: BattleStartRequest) => void;
  onMinimize?: () => void;
  sessionId: string;
  configPayload: BattleStartRequest['config'];
};

const TEMPLATE_GROUPS = ['流民小队', '暴徒小队', '野狗群', '持刀混混', '失控卫兵'];

export function BattleStartDialog({
  open,
  minimized = false,
  busy = false,
  currentZoneName,
  currentSubZoneName,
  subZoneDescription,
  dangerScore,
  reputationScore,
  onClose,
  onConfirm,
  onMinimize,
  sessionId,
  configPayload,
}: Props) {
  const [mode, setMode] = useState<'template' | 'ai_generated'>('template');
  const [templateGroup, setTemplateGroup] = useState<string>(TEMPLATE_GROUPS[0]);
  const [aiScale, setAiScale] = useState<'single' | 'squad'>('single');
  const [aiStrength, setAiStrength] = useState<'weak' | 'standard' | 'strong'>('standard');
  const [aiPacing, setAiPacing] = useState<'step' | 'auto'>('step');

  useEffect(() => {
    if (!open) return;
    setMode('template');
    setTemplateGroup(TEMPLATE_GROUPS[0]);
    setAiScale('single');
    setAiStrength('standard');
    setAiPacing('step');
  }, [open]);

  if (!open || minimized) return null;

  return (
    <div className="modal-mask">
      <div className="modal-card battle-start-dialog">
        <div className="modal-header-actions">
          <h3>开始战斗测试</h3>
          {onMinimize ? (
            <button type="button" onClick={onMinimize} disabled={busy}>
              暂时关闭
            </button>
          ) : null}
        </div>
        <p>战场会使用你当前所在的子区块，并在完整沙盒里运行，不写回正式玩法状态。</p>

        <div className="battle-start-summary">
          <p>
            当前战场: {currentZoneName} / {currentSubZoneName}
          </p>
          <p>子区块摘要: {subZoneDescription || '无'}</p>
          <p>
            区域危险: {typeof dangerScore === 'number' ? dangerScore : '-'} | 区域名声: {typeof reputationScore === 'number' ? reputationScore : '-'}
          </p>
        </div>

        <label>
          <span>怪物来源</span>
          <select value={mode} onChange={(e) => setMode(e.target.value as 'template' | 'ai_generated')} disabled={busy}>
            <option value="template">固定模板</option>
            <option value="ai_generated">AI 生成</option>
          </select>
        </label>

        {mode === 'template' ? (
          <label>
            <span>模板组</span>
            <select value={templateGroup} onChange={(e) => setTemplateGroup(e.target.value)} disabled={busy}>
              {TEMPLATE_GROUPS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <div className="battle-start-grid">
            <label>
              <span>生成规模</span>
              <select value={aiScale} onChange={(e) => setAiScale(e.target.value as 'single' | 'squad')} disabled={busy}>
                <option value="single">单敌</option>
                <option value="squad">小队</option>
              </select>
            </label>
            <label>
              <span>强度档</span>
              <select value={aiStrength} onChange={(e) => setAiStrength(e.target.value as 'weak' | 'standard' | 'strong')} disabled={busy}>
                <option value="weak">弱</option>
                <option value="standard">标准</option>
                <option value="strong">强</option>
              </select>
            </label>
          </div>
        )}

        <label>
          <span>AI 回合速度</span>
          <select value={aiPacing} onChange={(e) => setAiPacing(e.target.value as 'step' | 'auto')} disabled={busy}>
            <option value="step">逐单位暂停</option>
            <option value="auto">自动连走</option>
          </select>
        </label>

        <div className="actions">
          <button onClick={onClose} disabled={busy}>
            取消
          </button>
          <button
            onClick={() =>
              onConfirm({
                session_id: sessionId,
                mode,
                template_group: mode === 'template' ? templateGroup : null,
                ai_scale: aiScale,
                ai_strength: aiStrength,
                ai_pacing: aiPacing,
                config: configPayload,
              })
            }
            disabled={busy}
          >
            {busy ? '生成中...' : '开始测试战斗'}
          </button>
        </div>
      </div>
    </div>
  );
}
