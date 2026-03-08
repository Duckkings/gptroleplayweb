import type { NpcRoleCard } from '../types/app';

type Props = {
  open: boolean;
  role: NpcRoleCard | null;
  onClose: () => void;
};

const joinList = (items: string[]): string => (items.length > 0 ? items.join(', ') : '-');

export function RoleProfileModal({ open, role, onClose }: Props) {
  if (!open || !role) return null;

  const sheet = role.profile.dnd5e_sheet;
  const hp = sheet.hit_points;
  const relationSummary = role.relations.map((item) => `${item.target_role_id}:${item.relation_tag}`).join(', ') || '-';

  return (
    <div className="modal-mask">
      <div className="modal-card modal-wide role-profile-modal">
        <header className="inventory-modal-header">
          <div>
            <h3>队友完整属性</h3>
            <p>
              {role.name} | {role.role_id}
            </p>
          </div>
          <button onClick={onClose}>关闭</button>
        </header>

        <div className="role-profile-grid">
          <section className="role-profile-section">
            <h4>基础信息</h4>
            <p>状态: {role.state}</p>
            <p>区域: {role.zone_id ?? '-'} / {role.sub_zone_id ?? '-'}</p>
            <p>种族/职业: {sheet.race || '-'} / {sheet.char_class || '-'}</p>
            <p>背景/阵营: {sheet.background || '-'} / {sheet.alignment || '-'}</p>
            <p>等级: {sheet.level}</p>
          </section>

          <section className="role-profile-section">
            <h4>NPC 设定</h4>
            <p>性格: {role.personality || '-'}</p>
            <p>说话方式: {role.speaking_style || '-'}</p>
            <p>外观: {role.appearance || '-'}</p>
            <p>背景叙述: {role.background || '-'}</p>
            <p>认知: {role.cognition || '-'}</p>
            <p>秘密: {role.secret || '-'}</p>
            <p>喜好: {joinList(role.likes)}</p>
            <p>
              健谈值: {role.talkative_current} / {role.talkative_maximum}
            </p>
          </section>

          <section className="role-profile-section">
            <h4>数值与资源</h4>
            <p>
              HP: {hp.current} / {hp.maximum} (+{hp.temporary})
            </p>
            <p>
              体力: {sheet.stamina_current} / {sheet.stamina_maximum}
            </p>
            <p>
              AC / DC / 速度 / 先攻: {sheet.armor_class} / {sheet.difficulty_class} / {sheet.speed_ft} / {sheet.initiative_bonus}
            </p>
            <p>
              力敏体智感魅: {sheet.ability_scores.strength} / {sheet.ability_scores.dexterity} / {sheet.ability_scores.constitution} / {sheet.ability_scores.intelligence} / {sheet.ability_scores.wisdom} / {sheet.ability_scores.charisma}
            </p>
            <p>
              当前能力值: {sheet.current_ability_scores.strength} / {sheet.current_ability_scores.dexterity} / {sheet.current_ability_scores.constitution} / {sheet.current_ability_scores.intelligence} / {sheet.current_ability_scores.wisdom} / {sheet.current_ability_scores.charisma}
            </p>
          </section>

          <section className="role-profile-section">
            <h4>熟练与能力</h4>
            <p>豁免熟练: {joinList(sheet.saving_throws_proficient)}</p>
            <p>技能熟练: {joinList(sheet.skills_proficient)}</p>
            <p>语言: {joinList(sheet.languages)}</p>
            <p>工具熟练: {joinList(sheet.tool_proficiencies)}</p>
            <p>特性: {joinList(sheet.features_traits)}</p>
            <p>法术: {joinList(sheet.spells)}</p>
            <p>
              法术位: {sheet.spell_slots_current.level_1}/{sheet.spell_slots_max.level_1} | {sheet.spell_slots_current.level_2}/{sheet.spell_slots_max.level_2} | {sheet.spell_slots_current.level_3}/{sheet.spell_slots_max.level_3}
            </p>
            <p>备注: {sheet.notes || '-'}</p>
          </section>

          <section className="role-profile-section">
            <h4>社交与记忆</h4>
            <p>关系: {relationSummary}</p>
            <p>最近态度变化: {joinList(role.attitude_changes.slice(-5))}</p>
            <p>最近认知变化: {joinList(role.cognition_changes.slice(-5))}</p>
            <p>最近对话: {joinList(role.dialogue_logs.slice(-5).map((item) => `${item.speaker_name}:${item.content}`))}</p>
          </section>
        </div>
      </div>
    </div>
  );
}
