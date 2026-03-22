import { useRef } from 'react';
import type { ApiDebugEntry, PathStatus, TemplateLibraryStatusResponse } from '../types/app';

type Props = {
  onClose: () => void;
  entries: ApiDebugEntry[];
  configPath: PathStatus | null;
  savePath: PathStatus | null;
  onEnableMap: () => void;
  onOpenPlayerPanel: () => void;
  onOpenInventory: () => void;
  onOpenNpcPool: () => void;
  onOpenTeamPanel: () => void;
  onOpenCharacterBuildPlayer: () => void;
  onOpenCharacterBuildCompanion: () => void;
  playerBuildCompleted: boolean;
  onGenerateDebugTeammate: () => void;
  onOpenBattleStart: () => void;
  onFillTemplateLibrary: () => void;
  onFillSpellLibrary: () => void;
  onOpenActionPanel: () => void;
  onOpenPlayerInputValidationPanel: () => void;
  onGenerateQuest: () => void;
  onGenerateFate: () => void;
  onRegenerateFate: () => void;
  onOpenFatePanel: () => void;
  onShowConsistencyStatus: () => void;
  onRunConsistencyCheck: () => void;
  onGenerateEncounter: () => void;
  onSelectSaveFile: (file: File) => void;
  onClearSave: () => void;
  onDebugSaveReset: () => void;
  onPickSavePath: () => void;
  templateLibraryStatus: TemplateLibraryStatusResponse | null;
};

export function DebugPanel({
  onClose,
  entries,
  configPath,
  savePath,
  onEnableMap,
  onOpenPlayerPanel,
  onOpenInventory,
  onOpenNpcPool,
  onOpenTeamPanel,
  onOpenCharacterBuildPlayer,
  onOpenCharacterBuildCompanion,
  playerBuildCompleted,
  onGenerateDebugTeammate,
  onOpenBattleStart,
  onFillTemplateLibrary,
  onFillSpellLibrary,
  onOpenActionPanel,
  onOpenPlayerInputValidationPanel,
  onGenerateQuest,
  onGenerateFate,
  onRegenerateFate,
  onOpenFatePanel,
  onShowConsistencyStatus,
  onRunConsistencyCheck,
  onGenerateEncounter,
  onSelectSaveFile,
  onClearSave,
  onDebugSaveReset,
  onPickSavePath,
  templateLibraryStatus,
}: Props) {
  const saveInputRef = useRef<HTMLInputElement | null>(null);
  const runAndClose = (action: () => void) => () => {
    onClose();
    action();
  };

  return (
    <div className="debug-panel debug-panel-modal" role="dialog" aria-modal="true" aria-labelledby="debug-panel-title">
      <div className="debug-panel-header">
        <h3 id="debug-panel-title">Debug</h3>
        <button type="button" className="debug-close" onClick={onClose}>
          关闭
        </button>
      </div>

      <div className="debug-body">
        <div className="debug-actions">
          <button onClick={runAndClose(onEnableMap)}>世界地图</button>
          <button onClick={runAndClose(onOpenPlayerPanel)}>玩家数据</button>
          <button onClick={runAndClose(onOpenInventory)}>物品栏</button>
          <button onClick={runAndClose(onOpenNpcPool)}>NPC角色池</button>
          <button onClick={runAndClose(onOpenTeamPanel)}>当前队伍</button>
          <button onClick={runAndClose(onOpenCharacterBuildPlayer)} disabled={playerBuildCompleted}>
            创建玩家角色
          </button>
          <button onClick={runAndClose(onOpenCharacterBuildCompanion)} disabled={!playerBuildCompleted}>
            创建随从队友
          </button>
          <button onClick={runAndClose(onGenerateDebugTeammate)}>生成调试队友</button>
          <button onClick={runAndClose(onOpenBattleStart)}>开始战斗测试</button>
          <button onClick={runAndClose(onFillTemplateLibrary)}>AI 填充模板库</button>
          <button onClick={runAndClose(onFillSpellLibrary)}>AI 填充法术表</button>
          <button onClick={runAndClose(onOpenActionPanel)}>行为检定</button>
          <button onClick={runAndClose(onOpenPlayerInputValidationPanel)}>玩家行为校验测试</button>
          <button onClick={runAndClose(onGenerateQuest)}>生成任务</button>
          <button onClick={runAndClose(onGenerateFate)}>生成命运线</button>
          <button onClick={runAndClose(onRegenerateFate)}>重生成命运线</button>
          <button onClick={runAndClose(onOpenFatePanel)}>查看命运</button>
          <button onClick={runAndClose(onShowConsistencyStatus)}>一致性状态</button>
          <button onClick={runAndClose(onRunConsistencyCheck)}>执行一致性校验</button>
          <button onClick={runAndClose(onGenerateEncounter)}>立刻生成遭遇</button>
          <button onClick={() => saveInputRef.current?.click()}>选择存档文件</button>
          <input
            ref={saveInputRef}
            className="hidden-file-input"
            type="file"
            accept="application/json"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) {
                onClose();
                onSelectSaveFile(file);
              }
              e.currentTarget.value = '';
            }}
          />
          <button onClick={runAndClose(onPickSavePath)}>选择存档文件夹</button>
          <button onClick={runAndClose(onDebugSaveReset)}>测试重置</button>
          <button onClick={runAndClose(onClearSave)}>删除存档</button>
        </div>

        <div className="debug-paths">
          <p>配置路径: {configPath?.path ?? '未加载'}</p>
          <p>存档路径: {savePath?.path ?? '未加载'}</p>
          {templateLibraryStatus && (
            <>
              <p>
                {`模板库: 物品 ${templateLibraryStatus.item_definition_count} / 装备 ${templateLibraryStatus.equipment_definition_count} / 法术 ${templateLibraryStatus.spell_definition_count} / 武技 ${templateLibraryStatus.war_art_definition_count} / 交互 ${templateLibraryStatus.interactable_template_count}`}
              </p>
              <p>
                模板库: 物品 {templateLibraryStatus.item_definition_count} / 装备 {templateLibraryStatus.equipment_definition_count} / 法术 {templateLibraryStatus.spell_definition_count} / 交互 {templateLibraryStatus.interactable_template_count}
              </p>
              <p>模板库目录: {templateLibraryStatus.template_dir}</p>
            </>
          )}
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
    </div>
  );
}
