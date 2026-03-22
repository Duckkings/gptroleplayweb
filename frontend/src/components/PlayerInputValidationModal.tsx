import type { PlayerInputValidationResponse } from '../types/app';

type Props = {
  open: boolean;
  response: PlayerInputValidationResponse | null;
  originalActionText: string;
  originalSpeechText: string;
  onAcceptSuggestion: () => void;
  onReturnToEdit: () => void;
};

function renderTextBlock(label: string, value: string) {
  return (
    <div className="validation-text-block">
      <strong>{label}</strong>
      <p>{value.trim() || '无'}</p>
    </div>
  );
}

export function PlayerInputValidationModal({
  open,
  response,
  originalActionText,
  originalSpeechText,
  onAcceptSuggestion,
  onReturnToEdit,
}: Props) {
  if (!open || !response) return null;

  const suggestedActionText = response.fallback_action_text.trim();
  const suggestedSpeechText = response.normalized_speech_text.trim();
  const acceptDisabled = !suggestedActionText && !suggestedSpeechText;
  const resourceStatus = response.resource_status;

  return (
    <div className="roll-modal-mask" role="presentation">
      <div
        className="roll-modal-card validation-modal-card"
        onClick={(event) => {
          event.stopPropagation();
        }}
        role="dialog"
        aria-modal="true"
      >
        <div className="roll-modal-header">
          <div>
            <h3>玩家输入校验</h3>
            <p>{response.summary || '当前输入需要确认后再提交。'}</p>
          </div>
        </div>

        <section className="validation-panel-block">
          <h4>原始输入</h4>
          <div className="validation-grid">
            {renderTextBlock('行为', originalActionText)}
            {renderTextBlock('语言', originalSpeechText)}
          </div>
        </section>

        <section className="validation-panel-block">
          <h4>问题列表</h4>
          {response.issues.length === 0 ? (
            <p className="hint">没有额外问题。</p>
          ) : (
            <ul className="validation-issue-list">
              {response.issues.map((issue) => (
                <li key={issue.code}>
                  <strong>{issue.code}</strong>
                  <span>{issue.message}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="validation-panel-block">
          <h4>资源校验</h4>
          <div className="validation-grid">
            {renderTextBlock('状态', resourceStatus.check_status)}
            {renderTextBlock('类型', resourceStatus.resource_kind)}
            {renderTextBlock('提及资源', resourceStatus.mentioned_name)}
            {renderTextBlock('解析资源', resourceStatus.resolved_name)}
          </div>
          {(resourceStatus.requirement_summary || resourceStatus.current_summary) && (
            <div className="validation-grid">
              {renderTextBlock('需求', resourceStatus.requirement_summary)}
              {renderTextBlock('当前', resourceStatus.current_summary)}
            </div>
          )}
        </section>

        <section className="validation-panel-block">
          <h4>规范化结果</h4>
          <div className="validation-grid">
            {renderTextBlock('规范化行为', response.normalized_action_text)}
            {renderTextBlock('规范化语言', response.normalized_speech_text)}
          </div>
        </section>

        <section className="validation-panel-block">
          <h4>建议提交</h4>
          <div className="validation-grid">
            {renderTextBlock('建议行为', suggestedActionText)}
            {renderTextBlock('建议语言', suggestedSpeechText)}
          </div>
        </section>

        <div className="actions">
          <button type="button" onClick={onReturnToEdit}>
            返回修改
          </button>
          <button type="button" onClick={onAcceptSuggestion} disabled={acceptDisabled}>
            采用建议
          </button>
        </div>
      </div>
    </div>
  );
}
