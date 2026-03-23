import type { RefObject } from 'react';

import type {
  EnvironmentRiskLevel,
  PublicTurnAttackPrompt,
  PublicTurnInformationCheckPrompt,
  PublicTurnInteractionPrompt,
  PublicTurnOpposedPlanResponse,
  PublicTurnOpposedPrompt,
  PublicTurnPhase,
  RoleActionStatus,
} from '../types/app';

type TextareaRef = RefObject<HTMLTextAreaElement | null>;

type SummaryFields = {
  phase: PublicTurnPhase;
  roundNumber?: number | null;
  currentActorName?: string | null;
  riskLevel: EnvironmentRiskLevel;
  situationValue?: number | null;
};

type AwaitingEntryState = SummaryFields & {
  kind: 'awaiting_entry_controls';
  busy: boolean;
  onStartNextRound: () => void;
  onStartInitiative: () => void;
};

type AwaitingPlayerActionState = SummaryFields & {
  kind: 'awaiting_player_action';
  busy: boolean;
  playerActionStatus: RoleActionStatus;
  actionValue: string;
  speechValue: string;
  actionInputRef?: TextareaRef;
  onActionChange: (value: string) => void;
  onSpeechChange: (value: string) => void;
  onSubmit: () => void;
};

type InteractionResponseState = {
  kind: 'interaction_response';
  prompt: PublicTurnInteractionPrompt;
  busy: boolean;
  errorMessage: string;
  speechOnly: boolean;
  actionValue: string;
  speechValue: string;
  actionInputRef?: TextareaRef;
  onActionChange: (value: string) => void;
  onSpeechChange: (value: string) => void;
  onSubmit: () => void;
  onNoAction: () => void;
};

type AttackResponseState = {
  kind: 'attack_response';
  prompt: PublicTurnAttackPrompt;
  busy: boolean;
  errorMessage: string;
  speechOnly: boolean;
  actionValue: string;
  speechValue: string;
  actionInputRef?: TextareaRef;
  onActionChange: (value: string) => void;
  onSpeechChange: (value: string) => void;
  onSubmit: () => void;
  onNoAction: () => void;
};

type OpposedPlanningState = {
  kind: 'opposed_planning';
  prompt: PublicTurnOpposedPrompt;
  plan: PublicTurnOpposedPlanResponse | null;
  phase: 'ready' | 'rolling' | 'resolving' | 'resolved' | 'error';
  rollModalOpen: boolean;
  errorMessage: string;
  actionValue: string;
  speechValue: string;
  actionInputRef?: TextareaRef;
  onActionChange: (value: string) => void;
  onSpeechChange: (value: string) => void;
  onPlan: () => void;
  onTriggerRoll: () => void;
};

type InformationCheckPendingState = {
  kind: 'information_check_pending';
  prompt: PublicTurnInformationCheckPrompt;
};

export type PublicTurnInlinePromptState =
  | AwaitingEntryState
  | AwaitingPlayerActionState
  | InteractionResponseState
  | AttackResponseState
  | OpposedPlanningState
  | InformationCheckPendingState;

type Props = {
  state: PublicTurnInlinePromptState;
};

function formatModifier(value: number | null | undefined): string {
  const safeValue = typeof value === 'number' ? value : 0;
  return safeValue >= 0 ? `+${safeValue}` : `${safeValue}`;
}

function attackKindLabel(kind: PublicTurnAttackPrompt['attack_kind']): string {
  return kind === 'aoe_attack' ? '范围攻击' : '指定目标攻击';
}

function attackBasisLabel(basis: PublicTurnAttackPrompt['attack_basis']): string {
  if (basis === 'spell') return '法术';
  if (basis === 'weapon') return '武器';
  return '其他';
}

function attackAreaSummary(prompt: PublicTurnAttackPrompt): string | null {
  if (prompt.attack_kind !== 'aoe_attack') return null;
  if (prompt.attack_area_shape === 'sphere' || prompt.attack_area_shape === 'burst' || prompt.attack_area_shape === 'emanation') {
    return `${prompt.attack_area_shape} / 半径 ${prompt.attack_area_radius_m} 米`;
  }
  if (prompt.attack_area_shape === 'cone' || prompt.attack_area_shape === 'line') {
    return `${prompt.attack_area_shape} / 长度 ${prompt.attack_area_length_m} 米`;
  }
  return prompt.attack_area_shape;
}

function canSubmitTextResponse(speechOnly: boolean, actionValue: string, speechValue: string): boolean {
  if (speechOnly) {
    return speechValue.trim().length > 0;
  }
  return actionValue.trim().length > 0 || speechValue.trim().length > 0;
}

type ResponseComposerProps = {
  title: string;
  actionLabel?: string;
  speechLabel?: string;
  actionValue: string;
  speechValue: string;
  actionPlaceholder: string;
  speechPlaceholder: string;
  busy: boolean;
  disabled?: boolean;
  speechOnly?: boolean;
  errorMessage?: string;
  actionInputRef?: TextareaRef;
  submitLabel: string;
  submitDisabled: boolean;
  secondaryAction?: { label: string; onClick: () => void; disabled?: boolean };
  primaryAction: () => void;
  onActionChange: (value: string) => void;
  onSpeechChange: (value: string) => void;
};

function ResponseComposer({
  title,
  actionLabel = '行为',
  speechLabel = '语言',
  actionValue,
  speechValue,
  actionPlaceholder,
  speechPlaceholder,
  busy,
  disabled = false,
  speechOnly = false,
  errorMessage = '',
  actionInputRef,
  submitLabel,
  submitDisabled,
  secondaryAction,
  primaryAction,
  onActionChange,
  onSpeechChange,
}: ResponseComposerProps) {
  return (
    <section className="public-turn-inline-editor">
      <h4>{title}</h4>
      <div className="composer-input-grid">
        <div className="composer-input-block">
          <label htmlFor="public-turn-inline-action">{actionLabel}</label>
          <textarea
            id="public-turn-inline-action"
            ref={actionInputRef}
            rows={4}
            value={actionValue}
            onChange={(event) => onActionChange(event.target.value)}
            placeholder={actionPlaceholder}
            disabled={busy || disabled || speechOnly}
          />
        </div>
        <div className="composer-input-block">
          <label htmlFor="public-turn-inline-speech">{speechLabel}</label>
          <textarea
            id="public-turn-inline-speech"
            rows={4}
            value={speechValue}
            onChange={(event) => onSpeechChange(event.target.value)}
            placeholder={speechPlaceholder}
            disabled={busy || disabled}
          />
        </div>
      </div>
      {speechOnly ? <p className="hint">当前状态下不能输入会改变世界的行为，只能输入语言。</p> : null}
      {errorMessage ? <p className="error">{errorMessage}</p> : null}
      <div className="actions public-turn-inline-actions">
        {secondaryAction ? (
          <button type="button" onClick={secondaryAction.onClick} disabled={busy || disabled || secondaryAction.disabled}>
            {secondaryAction.label}
          </button>
        ) : null}
        <button type="button" onClick={primaryAction} disabled={busy || disabled || submitDisabled}>
          {busy ? '处理中...' : submitLabel}
        </button>
      </div>
    </section>
  );
}

export function PublicTurnInlinePromptPanel({ state }: Props) {
  if (state.kind === 'awaiting_entry_controls') {
    return (
      <section className="public-turn-inline-panel">
        <header className="public-turn-inline-header">
          <h4>公开回合</h4>
          <p>直接在这里推进公开回合，当前状态摘要已经移动到上方主聊天区域。</p>
        </header>
        <div className="actions public-turn-inline-actions">
          <button type="button" disabled={state.busy} onClick={state.onStartNextRound}>
            开始下一回合
          </button>
          <button type="button" disabled={state.busy} onClick={state.onStartInitiative}>
            优先行动
          </button>
        </div>
      </section>
    );
  }

  if (state.kind === 'awaiting_player_action') {
    const speechOnly = state.playerActionStatus === 'death_saving' || state.playerActionStatus === 'unable_to_act';
    const title = state.playerActionStatus === 'death_saving' ? '提交语言并进入死亡豁免' : '提交本阶段行动';
    const submitLabel = state.playerActionStatus === 'death_saving' ? '提交语言并掷死亡豁免' : '提交行动';

    return (
      <section className="public-turn-inline-panel">
        <header className="public-turn-inline-header">
          <h4>当前回合输入</h4>
          <p>直接在叙述区填写这轮动作和台词，提交后继续公开回合。</p>
        </header>
        <ResponseComposer
          title={title}
          actionValue={state.actionValue}
          speechValue={state.speechValue}
          actionPlaceholder={speechOnly ? '当前状态下不能输入会改变世界的行动。' : '例如：我快步抢到前排，用盾牌压住缺口。'}
          speechPlaceholder={
            state.playerActionStatus === 'death_saving'
              ? '例如：我咬牙说道：“我还没倒下。”'
              : '例如：先稳住阵线，别让局势继续失控。'
          }
          busy={state.busy}
          speechOnly={speechOnly}
          actionInputRef={state.actionInputRef}
          submitLabel={submitLabel}
          submitDisabled={!canSubmitTextResponse(speechOnly, state.actionValue, state.speechValue)}
          primaryAction={state.onSubmit}
          onActionChange={state.onActionChange}
          onSpeechChange={state.onSpeechChange}
        />
      </section>
    );
  }

  if (state.kind === 'interaction_response') {
    const canSubmit = canSubmitTextResponse(state.speechOnly, state.actionValue, state.speechValue);

    return (
      <section className="public-turn-inline-panel">
        <header className="public-turn-inline-header">
          <h4>公开回合互动</h4>
          <p>先回应这次互动，再继续本轮公开结算。</p>
        </header>
        <section className="public-turn-inline-context">
          <p>发起者: {state.prompt.source_actor_name}</p>
          <p>需要回应者: {state.prompt.target_actor_name}</p>
          {state.prompt.source_action_target_name ? <p>动作对象: {state.prompt.source_action_target_name}</p> : null}
          <p>对方行为: {state.prompt.source_action_summary}</p>
          {state.prompt.source_speech_text ? <p>对方语言: {state.prompt.source_speech_text}</p> : null}
          {state.prompt.source_speech_target_name ? <p>说话对象: {state.prompt.source_speech_target_name}</p> : null}
        </section>
        <ResponseComposer
          title="你的回应"
          actionValue={state.actionValue}
          speechValue={state.speechValue}
          actionPlaceholder="描述你如何回应这次互动。"
          speechPlaceholder="可选：你当场说了什么？"
          busy={state.busy}
          speechOnly={state.speechOnly}
          errorMessage={state.errorMessage}
          actionInputRef={state.actionInputRef}
          submitLabel="提交回应"
          submitDisabled={!canSubmit}
          secondaryAction={{ label: '不做任何行动', onClick: state.onNoAction }}
          primaryAction={state.onSubmit}
          onActionChange={state.onActionChange}
          onSpeechChange={state.onSpeechChange}
        />
      </section>
    );
  }

  if (state.kind === 'attack_response') {
    const canSubmit = canSubmitTextResponse(state.speechOnly, state.actionValue, state.speechValue);
    const areaText = attackAreaSummary(state.prompt);

    return (
      <section className="public-turn-inline-panel">
        <header className="public-turn-inline-header">
          <h4>公开回合攻击回应</h4>
          <p>先说明你如何处理这次攻击，若需要再进入后续掷骰。</p>
        </header>
        <section className="public-turn-inline-context">
          <p>攻击者: {state.prompt.source_actor_name}</p>
          <p>当前目标: {state.prompt.current_target_name}</p>
          <p>
            攻击分类: {attackKindLabel(state.prompt.attack_kind)} / {attackBasisLabel(state.prompt.attack_basis)}
          </p>
          {state.prompt.attack_definition_name ? <p>攻击定义: {state.prompt.attack_definition_name}</p> : null}
          <p>攻击行为: {state.prompt.source_action_summary}</p>
          {state.prompt.source_speech_text ? <p>攻击方语言: {state.prompt.source_speech_text}</p> : null}
          {areaText ? <p>范围说明: {areaText}</p> : null}
          <p>危险目标: {state.prompt.threatened_target_names.join('、') || '无'}</p>
          {state.prompt.revealed_target_names.length > 0 ? <p>本次显形目标: {state.prompt.revealed_target_names.join('、')}</p> : null}
          {state.prompt.can_include_self ? <p>这次攻击可能波及施术者自身。</p> : null}
          {state.prompt.player_in_danger ? <p>你当前处于这次攻击的影响范围内。</p> : null}
          {state.prompt.suggested_response_hint ? <p>回应提示: {state.prompt.suggested_response_hint}</p> : null}
        </section>
        <ResponseComposer
          title="你的处理"
          actionValue={state.actionValue}
          speechValue={state.speechValue}
          actionPlaceholder="你准备如何处理这次攻击？"
          speechPlaceholder="可选：你当场说了什么？"
          busy={state.busy}
          speechOnly={state.speechOnly}
          errorMessage={state.errorMessage}
          actionInputRef={state.actionInputRef}
          submitLabel="提交回应"
          submitDisabled={!canSubmit}
          secondaryAction={{ label: '不做任何行动', onClick: state.onNoAction }}
          primaryAction={state.onSubmit}
          onActionChange={state.onActionChange}
          onSpeechChange={state.onSpeechChange}
        />
      </section>
    );
  }

  if (state.kind === 'information_check_pending') {
    return (
      <section className="public-turn-inline-panel">
        <header className="public-turn-inline-header">
          <h4>信息检定待完成</h4>
          <p>先完成这次信息检定掷骰，再继续当前公开回合结算。</p>
        </header>
        <section className="public-turn-inline-context">
          {state.prompt.source_actor_name ? <p>相关对象: {state.prompt.source_actor_name}</p> : null}
          <p>检定目标: {state.prompt.check_task || '获取当前线索'}</p>
          <p>属性: {state.prompt.ability_used} / DC {state.prompt.dc}</p>
          {state.prompt.stakes_summary ? <p>局势摘要: {state.prompt.stakes_summary}</p> : null}
        </section>
      </section>
    );
  }

  const planning = state.phase === 'resolving' && state.plan === null;
  const canEdit = !planning && !state.rollModalOpen;
  const canRoll = state.phase === 'ready' && state.plan !== null && !state.rollModalOpen;

  return (
    <section className="public-turn-inline-panel">
      <header className="public-turn-inline-header">
        <h4>公开回合对抗</h4>
        <p>先确认你的回应和对抗规划，再开始掷出这次对抗的 d20。</p>
      </header>
      <section className="public-turn-inline-context">
        <p>发起者: {state.prompt.source_actor_name}</p>
        <p>目标: {state.prompt.target_actor_name}</p>
        <p>对方行为: {state.prompt.source_action_summary}</p>
        {state.prompt.source_speech_text ? <p>对方语言: {state.prompt.source_speech_text}</p> : null}
        {state.prompt.source_speech_target_name && state.prompt.source_speech_target_name !== state.prompt.target_actor_name ? (
          <p>说话对象: {state.prompt.source_speech_target_name}</p>
        ) : null}
        <p>对抗焦点: {state.prompt.stakes_summary}</p>
      </section>
      <ResponseComposer
        title="你的回应"
        actionValue={state.actionValue}
        speechValue={state.speechValue}
        actionPlaceholder="你准备如何对抗这次动作？"
        speechPlaceholder="可选：你在对抗时说了什么？"
        busy={planning}
        disabled={!canEdit}
        errorMessage={state.errorMessage}
        actionInputRef={state.actionInputRef}
        submitLabel={state.plan ? '重新规划对抗' : '规划对抗'}
        submitDisabled={false}
        primaryAction={state.onPlan}
        onActionChange={state.onActionChange}
        onSpeechChange={state.onSpeechChange}
      />
      {state.plan ? (
        <section className="public-turn-inline-plan">
          <p>对抗任务: {state.plan.check_task}</p>
          <div className="public-turn-inline-plan-grid">
            <p>
              对方属性: {state.plan.source_ability_used} {formatModifier(state.plan.source_ability_modifier)}
            </p>
            <p>
              你的属性: {state.plan.target_ability_used} {formatModifier(state.plan.target_ability_modifier)}
            </p>
          </div>
          <p>对方动作摘要: {state.plan.source_action_summary}</p>
          <p>你的动作摘要: {state.plan.target_action_summary}</p>
          {state.plan.target_speech_text ? <p>你的语言: {state.plan.target_speech_text}</p> : null}
          <div className="actions public-turn-inline-actions">
            <button type="button" onClick={state.onTriggerRoll} disabled={!canRoll}>
              开始掷骰
            </button>
          </div>
        </section>
      ) : null}
      {planning ? <p className="hint">正在规划这次对抗...</p> : null}
    </section>
  );
}
