import { getCharacterBuildAssetUrl } from '../services/api';
import type { RoleActionStatus } from '../types/app';

export type PartyPreviewEntry = {
  id: string;
  kind: 'player' | 'teammate';
  name: string;
  portraitAssetId: string | null;
  hpCurrent: number;
  hpMax: number;
  tempHp: number;
  spellSlotsCurrent: number;
  spellSlotsMax: number;
  martialPointsCurrent: number;
  martialPointsMax: number;
  roleActionStatus: RoleActionStatus;
  retained: boolean;
  loading?: boolean;
};

type Props = {
  entries: PartyPreviewEntry[];
  onOpenPlayerPanel: () => void;
  onOpenTeamPanel: () => void;
  onSelectPlayer: () => void;
  onSelectTeammate: (roleId: string, roleName: string) => void;
};

const ROLE_STATUS_LABELS: Record<Exclude<RoleActionStatus, 'free_action'>, string> = {
  death_saving: '濒死',
  dead: '死亡',
  unable_to_act: '无法行动',
};

function initialsFromName(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return '?';
  return trimmed.slice(0, 2).toUpperCase();
}

export function PartyPreviewRail({
  entries,
  onOpenPlayerPanel,
  onOpenTeamPanel,
  onSelectPlayer,
  onSelectTeammate,
}: Props) {
  return (
    <aside className="party-preview-rail card">
      <header className="party-preview-header">
        <div className="party-preview-copy">
          <h2>队伍预览</h2>
          <p>玩家与当前队友的快捷入口。</p>
        </div>
        <div className="actions">
          <button type="button" onClick={onOpenPlayerPanel}>
            玩家数据
          </button>
          <button type="button" onClick={onOpenTeamPanel}>
            队伍详情
          </button>
        </div>
      </header>

      <div className="party-preview-list">
        {entries.map((entry) => {
          const backgroundImage = entry.portraitAssetId ? `url(${getCharacterBuildAssetUrl(entry.portraitAssetId)})` : undefined;
          const actionLabel = entry.kind === 'player' ? '打开玩家快捷操作' : `打开 ${entry.name} 的队友单聊`;
          const statusLabel =
            entry.roleActionStatus === 'free_action' ? null : ROLE_STATUS_LABELS[entry.roleActionStatus];

          return (
            <button
              key={entry.id}
              type="button"
              className={`party-card ${entry.loading ? 'is-loading' : ''}`}
              onClick={() =>
                entry.kind === 'player' ? onSelectPlayer() : onSelectTeammate(entry.id, entry.name)
              }
              aria-label={actionLabel}
            >
              {backgroundImage ? (
                <div className="party-card-portrait" style={{ backgroundImage }} />
              ) : (
                <div className="party-card-placeholder">{initialsFromName(entry.name)}</div>
              )}

              <div className="party-card-overlay">
                <div className="party-card-topline">
                  <span className="party-card-kind">{entry.kind === 'player' ? '玩家' : '队友'}</span>
                  {entry.retained && <span className="party-card-tag">已保留</span>}
                  {statusLabel && <span className="party-card-tag is-warning">{statusLabel}</span>}
                </div>

                <strong className="party-card-name">{entry.name}</strong>

                <div className="party-card-stats">
                  <span>HP {entry.hpCurrent}/{entry.hpMax}</span>
                  <span>法 {entry.spellSlotsCurrent}/{entry.spellSlotsMax}</span>
                  <span>武 {entry.martialPointsCurrent}/{entry.martialPointsMax}</span>
                  {entry.tempHp > 0 && <span>+{entry.tempHp} 临时</span>}
                </div>

                {entry.loading && <p className="hint">正在补载角色数据...</p>}
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
