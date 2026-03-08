import { useRef } from 'react';
import type { ApiDebugEntry, PathStatus } from '../types/app';

type Props = {
  collapsed: boolean;
  onToggle: () => void;
  entries: ApiDebugEntry[];
  configPath: PathStatus | null;
  savePath: PathStatus | null;
  onEnableMap: () => void;
  onOpenPlayerPanel: () => void;
  onOpenInventory: () => void;
  onOpenNpcPool: () => void;
  onOpenTeamPanel: () => void;
  onGenerateDebugTeammate: () => void;
  onOpenActionPanel: () => void;
  onGenerateQuest: () => void;
  onGenerateFate: () => void;
  onRegenerateFate: () => void;
  onOpenFatePanel: () => void;
  onShowConsistencyStatus: () => void;
  onRunConsistencyCheck: () => void;
  onToggleEncounterForce: () => void;
  encounterForceEnabled: boolean;
  onSelectSaveFile: (file: File) => void;
  onClearSave: () => void;
  onPickSavePath: () => void;
};

export function DebugPanel({
  collapsed,
  onToggle,
  entries,
  configPath,
  savePath,
  onEnableMap,
  onOpenPlayerPanel,
  onOpenInventory,
  onOpenNpcPool,
  onOpenTeamPanel,
  onGenerateDebugTeammate,
  onOpenActionPanel,
  onGenerateQuest,
  onGenerateFate,
  onRegenerateFate,
  onOpenFatePanel,
  onShowConsistencyStatus,
  onRunConsistencyCheck,
  onToggleEncounterForce,
  encounterForceEnabled,
  onSelectSaveFile,
  onClearSave,
  onPickSavePath,
}: Props) {
  const saveInputRef = useRef<HTMLInputElement | null>(null);

  return (
    <aside className={`debug-panel ${collapsed ? 'collapsed' : ''}`}>
      <button className="debug-toggle" onClick={onToggle}>
        {collapsed ? 'Debug' : '收起 Debug'}
      </button>
      {!collapsed && (
        <div className="debug-body">
          <div className="debug-actions">
            <button onClick={onEnableMap}>世界地图</button>
            <button onClick={onOpenPlayerPanel}>玩家数据</button>
            <button onClick={onOpenInventory}>物品栏</button>
            <button onClick={onOpenNpcPool}>NPC角色池</button>
            <button onClick={onOpenTeamPanel}>当前队伍</button>
            <button onClick={onGenerateDebugTeammate}>生成调试队友</button>
            <button onClick={onOpenActionPanel}>行为检定</button>
            <button onClick={onGenerateQuest}>生成任务</button>
            <button onClick={onGenerateFate}>生成命运线</button>
            <button onClick={onRegenerateFate}>重生成命运线</button>
            <button onClick={onOpenFatePanel}>查看命运</button>
            <button onClick={onShowConsistencyStatus}>一致性状态</button>
            <button onClick={onRunConsistencyCheck}>执行一致性校验</button>
            <button onClick={onToggleEncounterForce}>{encounterForceEnabled ? '关闭100%遭遇' : '开启100%遭遇'}</button>
            <button onClick={() => saveInputRef.current?.click()}>选择存档文件</button>
            <input
              ref={saveInputRef}
              className="hidden-file-input"
              type="file"
              accept="application/json"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) onSelectSaveFile(file);
                e.currentTarget.value = '';
              }}
            />
            <button onClick={onPickSavePath}>选择存档文件夹</button>
            <button onClick={onClearSave}>删除存档</button>
          </div>

          <div className="debug-paths">
            <p>配置路径: {configPath?.path ?? '未加载'}</p>
            <p>存档路径: {savePath?.path ?? '未加载'}</p>
          </div>

          <section className="debug-entries">
            {entries.length === 0 && <p className="hint">暂无 API 摘要。</p>}
            {entries.map((entry, idx) => (
              <article key={`${entry.endpoint}-${idx}`} className="debug-entry">
                <strong>{entry.endpoint}</strong>
                <p>
                  状态: {entry.status} | {entry.ok ? 'ok' : 'error'} | 时间: {entry.at}
                </p>
                {entry.usage && (
                  <p>
                    token in/out: {entry.usage.input_tokens}/{entry.usage.output_tokens}
                  </p>
                )}
                {entry.detail && <p className="error">{entry.detail}</p>}
              </article>
            ))}
          </section>
        </div>
      )}
    </aside>
  );
}
