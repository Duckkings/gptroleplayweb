import { LiveProgressPanel } from './LiveProgressPanel';
import { getCharacterBuildAssetUrl } from '../services/api';
import type { ChatMessage, LiveProgressEntry, NpcRoleCard, RoleActionStatus } from '../types/app';

type Props = {
  open: boolean;
  role: NpcRoleCard | null;
  affinity: number | null;
  trust: number | null;
  messages: ChatMessage[];
  liveProgress: LiveProgressEntry[];
  actionValue: string;
  speechValue: string;
  busy: boolean;
  inputDisabled: boolean;
  sendDisabled: boolean;
  disabledHint?: string;
  errorMessage?: string;
  onActionChange: (value: string) => void;
  onSpeechChange: (value: string) => void;
  onSend: () => void;
  onRetry: () => void;
  onOpenInventory: () => void;
  onOpenProfile: () => void;
  onRetain: () => void;
  memorySummaryBusy: boolean;
  memorySummaryAvailable: boolean;
  onGenerateMemorySummary: () => void;
  onClose: () => void;
};

const ROLE_STATUS_LABELS: Record<Exclude<RoleActionStatus, 'free_action'>, string> = {
  death_saving: '死亡豁免',
  dead: '死亡',
  unable_to_act: '无法行动',
};

function sumSpellSlots(slots: NpcRoleCard['profile']['dnd5e_sheet']['spell_slots_current']): number {
  return Object.values(slots).reduce((sum, value) => sum + Number(value || 0), 0);
}

function initialsFromName(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return '?';
  return trimmed.slice(0, 2).toUpperCase();
}

export function TeammateChatModal({
  open,
  role,
  affinity,
  trust,
  messages,
  liveProgress,
  actionValue,
  speechValue,
  busy,
  inputDisabled,
  sendDisabled,
  disabledHint,
  errorMessage,
  onActionChange,
  onSpeechChange,
  onSend,
  onRetry,
  onOpenInventory,
  onOpenProfile,
  onRetain,
  memorySummaryBusy,
  memorySummaryAvailable,
  onGenerateMemorySummary,
  onClose,
}: Props) {
  if (!open) return null;

  const sheet = role?.profile.dnd5e_sheet ?? null;
  const portraitAssetId = role?.portrait?.asset_id ?? role?.profile.portrait?.asset_id ?? null;
  const statusLabel =
    sheet && sheet.role_action_status !== 'free_action' ? ROLE_STATUS_LABELS[sheet.role_action_status] : null;

  return (
    <div className="modal-mask teammate-chat-mask">
      <div className="modal-card teammate-chat-modal">
        <div className="teammate-chat-layout">
          <aside className="teammate-chat-portrait-panel">
            {portraitAssetId ? (
              <div
                className="teammate-chat-portrait"
                style={{ backgroundImage: `url(${getCharacterBuildAssetUrl(portraitAssetId)})` }}
              />
            ) : (
              <div className="teammate-chat-portrait teammate-chat-portrait-placeholder">
                {initialsFromName(role?.name ?? '')}
              </div>
            )}

            <div className="teammate-chat-summary">
              <h3>{role?.name ?? '队友'}</h3>
              {role && sheet ? (
                <>
                  <div className="teammate-chat-summary-grid">
                    <p>
                      HP {sheet.hit_points.current}/{sheet.hit_points.maximum}
                      {sheet.hit_points.temporary > 0 ? ` (+${sheet.hit_points.temporary})` : ''}
                    </p>
                    <p>法术位 {sumSpellSlots(sheet.spell_slots_current)}/{sumSpellSlots(sheet.spell_slots_max)}</p>
                    <p>武技点 {sheet.martial_points_current}/{sheet.martial_points_maximum}</p>
                    <p>健谈值 {role.talkative_current}/{role.talkative_maximum}</p>
                    <p>好感度 {typeof affinity === 'number' ? affinity : '-'}</p>
                    <p>信任度 {typeof trust === 'number' ? trust : '-'}</p>
                  </div>
                  {statusLabel && <p className="hint">状态: {statusLabel}</p>}
                </>
              ) : (
                <p className="hint">正在载入队友数据...</p>
              )}
            </div>
          </aside>

          <section className="teammate-chat-main">
            <header className="teammate-chat-header">
              <div>
                <h3>队友单聊</h3>
                <p>{role ? `${role.name} / ${role.role_id}` : '读取中...'}</p>
              </div>
              <div className="actions">
                <button type="button" onClick={onOpenInventory} disabled={!role}>
                  背包
                </button>
                <button type="button" onClick={onOpenProfile} disabled={!role}>
                  属性
                </button>
                <button type="button" onClick={onRetain} disabled={!role || Boolean(role?.retained_id)}>
                  {role?.retained_id ? '已保留' : '保留'}
                </button>
                <button type="button" onClick={onGenerateMemorySummary} disabled={!memorySummaryAvailable || memorySummaryBusy || busy}>
                  {memorySummaryBusy ? '生成中...' : '生成记忆摘要'}
                </button>
                <button type="button" onClick={onClose} disabled={busy || memorySummaryBusy}>
                  关闭
                </button>
              </div>
            </header>

            <section className="messages teammate-chat-messages">
              {messages.length === 0 && <p className="hint">你已接近该队友，可以只输入动作或只输入语言开始交互。</p>}
              {messages.map((message, index) => (
                <article key={`${message.role}_${index}`} className={`msg ${message.role}`}>
                  <strong>{message.role === 'user' ? '你' : message.role === 'assistant' ? 'GM' : 'System'}</strong>
                  <p>{message.content}</p>
                </article>
              ))}
              <LiveProgressPanel entries={liveProgress} compact />
            </section>

            <footer className="composer teammate-chat-composer">
              <div className="actions">
                <button type="button" onClick={onRetry} disabled={busy}>
                  重新填回
                </button>
              </div>

              <div className="composer-input-grid">
                <div className="composer-input-block">
                  <label htmlFor="teammate-chat-action">动作描述</label>
                  <textarea
                    id="teammate-chat-action"
                    value={actionValue}
                    onChange={(event) => onActionChange(event.target.value)}
                    placeholder="例如：我把药水递给你，示意你先喝下去。"
                    disabled={busy || inputDisabled}
                  />
                </div>
                <div className="composer-input-block">
                  <label htmlFor="teammate-chat-speech">语言描述</label>
                  <textarea
                    id="teammate-chat-speech"
                    value={speechValue}
                    onChange={(event) => onSpeechChange(event.target.value)}
                    placeholder="例如：我低声说：先稳住，我们之后再谈。"
                    disabled={busy || inputDisabled}
                  />
                </div>
              </div>

              {disabledHint && <p className="hint">{disabledHint}</p>}
              {errorMessage && <p className="error">{errorMessage}</p>}

              <div className="actions">
                <button type="button" onClick={onSend} disabled={busy || sendDisabled}>
                  {busy ? '发送中...' : '发送'}
                </button>
              </div>
            </footer>
          </section>
        </div>
      </div>
    </div>
  );
}
