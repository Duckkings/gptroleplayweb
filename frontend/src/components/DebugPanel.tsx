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
  onOpenNpcPool: () => void;
  onOpenActionPanel: () => void;
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
  onOpenNpcPool,
  onOpenActionPanel,
  onSelectSaveFile,
  onClearSave,
  onPickSavePath,
}: Props) {
  const saveInputRef = useRef<HTMLInputElement | null>(null);

  return (
    <aside className={`debug-panel ${collapsed ? 'collapsed' : ''}`}>
      <button onClick={onToggle}>{collapsed ? 'Debug' : '收起 Debug'}</button>
      {!collapsed && (
        <div className="debug-body">
          <div className="actions">
            <button onClick={onEnableMap}>世界地图</button>
            <button onClick={onOpenPlayerPanel}>玩家数据</button>
            <button onClick={onOpenNpcPool}>NPC角色池</button>
            <button onClick={onOpenActionPanel}>行为检定</button>
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
