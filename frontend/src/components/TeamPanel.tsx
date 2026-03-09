import { useMemo, useState } from 'react';
import type { NpcRoleCard, TeamChatReply, TeamState } from '../types/app';

type Props = {
  open: boolean;
  state: TeamState;
  roleCards: NpcRoleCard[];
  chatReplies: TeamChatReply[];
  chatBusy: boolean;
  chatBlocked?: boolean;
  onRefresh: () => void;
  onTeamChat: (playerMessage: string) => void;
  onChat: (npcId: string, npcName: string) => void;
  onInspectProfile: (npcId: string) => void;
  onInspectInventory: (npcId: string) => void;
  onLeave: (npcId: string) => void;
  onClose: () => void;
};

export function TeamPanel({
  open,
  state,
  roleCards,
  chatReplies,
  chatBusy,
  chatBlocked = false,
  onRefresh,
  onTeamChat,
  onChat,
  onInspectProfile,
  onInspectInventory,
  onLeave,
  onClose,
}: Props) {
  const [teamChatInput, setTeamChatInput] = useState('');
  const roleMap = useMemo(() => new Map(roleCards.map((item) => [item.role_id, item])), [roleCards]);

  if (!open) return null;

  return (
    <section className="npc-pool-panel card team-panel">
      <header className="chat-header">
        <div>
          <h2>当前队伍</h2>
          <p>成员 {state.members.length}，可发起队伍聊天、查看队友属性与背包，并进入单聊。</p>
        </div>
        <div className="actions">
          <button onClick={onRefresh}>刷新</button>
          <button onClick={onClose}>关闭</button>
        </div>
      </header>

      <section className="team-chat-box">
        <h3>队伍聊天</h3>
        <textarea
          value={teamChatInput}
          onChange={(e) => setTeamChatInput(e.target.value)}
          placeholder="输入想对当前所有队友说的话。"
          disabled={chatBusy || chatBlocked}
        />
        <div className="actions">
          <button
            onClick={() => {
              const next = teamChatInput.trim();
              if (!next) return;
              onTeamChat(next);
              setTeamChatInput('');
            }}
            disabled={chatBusy || chatBlocked || state.members.length === 0 || !teamChatInput.trim()}
          >
            {chatBusy ? '发送中...' : '发送队伍聊天'}
          </button>
        </div>
        <div className="team-chat-feed">
          {chatReplies.length === 0 && <p className="hint">本轮还没有队伍聊天回应。</p>}
          {chatReplies.map((reply) => (
            <article key={`${reply.member_role_id}_${reply.created_at}`} className="consistency-item">
              <strong>
                {reply.member_name} / {reply.response_mode === 'action' ? '动作' : '发言'}
              </strong>
              <p>{reply.content}</p>
              <p>
                好感变化 {reply.affinity_delta} | 信任变化 {reply.trust_delta}
              </p>
            </article>
          ))}
        </div>
      </section>

      <div className="team-layout">
        <section className="team-member-list">
          {state.members.length === 0 && <p className="hint">当前没有队友。</p>}
          {state.members.map((member) => {
            const role = roleMap.get(member.role_id) ?? null;
            const inventory = role?.profile.dnd5e_sheet.backpack;
            return (
              <article key={member.role_id} className="team-member-card">
                <div className="team-member-head">
                  <div>
                    <strong>{member.name}</strong>
                    <p>{member.role_id}</p>
                  </div>
                  <div className="actions">
                    <button onClick={() => onChat(member.role_id, member.name)} disabled={chatBlocked}>
                      单聊
                    </button>
                    <button onClick={() => onInspectProfile(member.role_id)} disabled={!role}>
                      属性
                    </button>
                    <button onClick={() => onInspectInventory(member.role_id)} disabled={!role}>
                      背包
                    </button>
                    <button onClick={() => onLeave(member.role_id)}>离队</button>
                  </div>
                </div>
                <p>
                  好感/信任: {member.affinity} / {member.trust}
                </p>
                <p>加入来源: {member.join_source === 'debug' ? '调试生成' : '正常招募'}</p>
                <p>加入原因: {member.join_reason || '-'}</p>
                <p>
                  原始位置: {member.origin_zone_id ?? '-'} / {member.origin_sub_zone_id ?? '-'}
                </p>
                <p>最近反应: {member.last_reaction_preview || '暂无'}</p>
                {role && (
                  <>
                    <p>状态: {role.state}</p>
                    <p>性格: {role.personality || '-'}</p>
                    <p>说话方式: {role.speaking_style || '-'}</p>
                    <p>
                      种族/职业: {role.profile.dnd5e_sheet.race || '-'} / {role.profile.dnd5e_sheet.char_class || '-'}
                    </p>
                    <p>背包金币: {inventory?.gold ?? 0}</p>
                    <p>背包物品: {(inventory?.items ?? []).map((item) => item.name).join(', ') || '无'}</p>
                    <p>欲望: {role.desires.map((item) => `${item.title}(${item.status})`).join(' / ') || '暂无'}</p>
                    <p>故事节点: {role.story_beats.map((item) => `${item.title}(${item.status})`).join(' / ') || '暂无'}</p>
                  </>
                )}
              </article>
            );
          })}
        </section>

        <section className="team-reaction-list">
          <h3>最近队伍反应</h3>
          {state.reactions.length === 0 && <p className="hint">暂无反应记录。</p>}
          {state.reactions
            .slice()
            .reverse()
            .slice(0, 20)
            .map((reaction) => (
              <article key={reaction.reaction_id} className="consistency-item">
                <strong>
                  {reaction.member_name} / {reaction.trigger_kind}
                </strong>
                <p>{reaction.content}</p>
                <p>
                  好感变化 {reaction.affinity_delta} | 信任变化 {reaction.trust_delta}
                </p>
                <p>{reaction.created_at}</p>
              </article>
            ))}
        </section>
      </div>
    </section>
  );
}
