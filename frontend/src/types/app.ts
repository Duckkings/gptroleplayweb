export type UIConfig = {
  theme: string;
};

export type AppConfig = {
  version: string;
  openai_api_key: string;
  model: string;
  stream: boolean;
  temperature: number;
  max_tokens: number;
  gm_prompt: string;
  speech_time_per_50_tokens_min: number;
  ui?: UIConfig;
};

export type ChatRole = 'user' | 'assistant' | 'system';

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type Usage = {
  input_tokens: number;
  output_tokens: number;
};

export type TokenUsageBucket = {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
};

export type TokenUsageSummary = {
  session_id: string;
  total: TokenUsageBucket;
  sources: {
    chat: TokenUsageBucket;
    map_generation: TokenUsageBucket;
    movement_narration: TokenUsageBucket;
  };
};

export type ChatResponse = {
  session_id: string;
  reply: ChatMessage;
  usage: Usage;
  tool_events?: ToolEvent[];
  time_spent_min: number;
};

export type ToolEvent = {
  tool_name: string;
  ok: boolean;
  summary: string;
  payload: Record<string, string | number | boolean>;
};

export type ApiDebugEntry = {
  endpoint: string;
  status: number;
  ok: boolean;
  at: string;
  usage?: Usage;
  detail?: string;
};

export type PathStatus = {
  path: string;
  exists: boolean;
  writable: boolean;
};

export type Position = {
  x: number;
  y: number;
  z: number;
  zone_id: string;
};

export type Zone = {
  zone_id: string;
  name: string;
  x: number;
  y: number;
  z: number;
  zone_type: string;
  size: 'small' | 'medium' | 'large';
  radius_m: number;
  description: string;
  tags: string[];
  sub_zones: Array<{
    name: string;
    offset_x: number;
    offset_y: number;
    offset_z: number;
    description: string;
  }>;
};

export type MapSnapshot = {
  player_position: Position | null;
  zones: Zone[];
};

export type PlayerStaticData = {
  player_id: string;
  name: string;
  move_speed_mph: number;
  role_type: 'player' | 'npc' | 'monster';
  dnd5e_sheet: Dnd5eCharacterSheet;
};

export type PlayerRuntimeData = {
  session_id: string;
  current_position: Position | null;
  updated_at: string;
};

export type SaveFile = {
  version: string;
  session_id: string;
  map_snapshot: MapSnapshot;
  area_snapshot: AreaSnapshot;
  game_logs: GameLogEntry[];
  game_log_settings: GameLogSettings;
  player_static_data: PlayerStaticData;
  player_runtime_data: PlayerRuntimeData;
  role_pool: NpcRoleCard[];
  updated_at: string;
};

export type Coord3D = {
  x: number;
  y: number;
  z: number;
};

export type WorldClock = {
  calendar: string;
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  updated_at: string;
};

export type AreaInteraction = {
  interaction_id: string;
  name: string;
  type: 'item' | 'npc' | 'scene';
  status: 'ready' | 'disabled' | 'hidden';
  generated_mode: 'pre' | 'instant';
  placeholder: boolean;
};

export type AreaNpc = {
  npc_id: string;
  name: string;
  state: string;
};

export type AreaSubZone = {
  sub_zone_id: string;
  zone_id: string;
  name: string;
  coord: Coord3D;
  radius_m: number;
  description: string;
  generated_mode: 'pre' | 'instant';
  key_interactions: AreaInteraction[];
  npcs: AreaNpc[];
};

export type AreaZone = {
  zone_id: string;
  name: string;
  zone_type: string;
  size: 'small' | 'medium' | 'large';
  center: Coord3D;
  radius_m: number;
  description: string;
  sub_zone_ids: string[];
};

export type AreaSnapshot = {
  version: string;
  zones: AreaZone[];
  sub_zones: AreaSubZone[];
  current_zone_id: string | null;
  current_sub_zone_id: string | null;
  clock: WorldClock | null;
};

export type AreaMoveResult = {
  ok: boolean;
  from_point: {
    zone_id: string;
    sub_zone_id?: string | null;
    coord: Coord3D;
  };
  to_point: {
    zone_id: string;
    sub_zone_id?: string | null;
    coord: Coord3D;
  };
  distance_m: number;
  duration_min: number;
  clock_delta_min: number;
  clock_after: WorldClock;
  movement_feedback: string;
};

export type RenderNode = {
  zone_id: string;
  name: string;
  x: number;
  y: number;
};

export type RenderResult = {
  session_id: string;
  viewport: {
    min_x: number;
    max_x: number;
    min_y: number;
    max_y: number;
  };
  nodes: RenderNode[];
  sub_nodes: Array<{
    sub_zone_id: string;
    zone_id: string;
    name: string;
    x: number;
    y: number;
  }>;
  circles: Array<{
    zone_id: string;
    center_x: number;
    center_y: number;
    radius_m: number;
  }>;
  player_marker: { x: number; y: number };
};

export type MovementLog = {
  id: string;
  summary: string;
  payload: Record<string, string | number>;
  created_at: string;
};

export type GameLogEntry = {
  id: string;
  session_id: string;
  kind: string;
  message: string;
  payload: Record<string, string | number | boolean>;
  created_at: string;
};

export type GameLogSettings = {
  ai_fetch_limit: number;
};

export type Dnd5eAbilityScores = {
  strength: number;
  dexterity: number;
  constitution: number;
  intelligence: number;
  wisdom: number;
  charisma: number;
};

export type Dnd5eAbilityModifiers = {
  strength: number;
  dexterity: number;
  constitution: number;
  intelligence: number;
  wisdom: number;
  charisma: number;
};

export type Dnd5eHitPoints = {
  current: number;
  maximum: number;
  temporary: number;
};

export type Dnd5eSpellSlots = {
  level_1: number;
  level_2: number;
  level_3: number;
  level_4: number;
  level_5: number;
  level_6: number;
  level_7: number;
  level_8: number;
  level_9: number;
};

export type RoleBuffEffect = {
  strength_delta: number;
  dexterity_delta: number;
  constitution_delta: number;
  intelligence_delta: number;
  wisdom_delta: number;
  charisma_delta: number;
  ac_delta: number;
  dc_delta: number;
  speed_ft_delta: number;
  move_speed_mph_delta: number;
  hp_max_delta: number;
  stamina_max_delta: number;
};

export type RoleBuff = {
  buff_id: string;
  name: string;
  description: string;
  source: string;
  duration_min: number;
  remaining_min: number;
  stackable: boolean;
  effect: RoleBuffEffect;
};

export type InventoryItem = {
  item_id: string;
  name: string;
  item_type: string;
  description: string;
  weight: number;
  rarity: string;
  value: number;
  effect: string;
  uses_max: number | null;
  uses_left: number | null;
  cooldown_min: number;
  bound: boolean;
  quantity: number;
  slot_type: 'weapon' | 'armor' | 'misc';
  attack_bonus: number;
  armor_bonus: number;
};

export type InventoryData = {
  gold: number;
  items: InventoryItem[];
};

export type EquipmentSlots = {
  weapon_item_id: string | null;
  armor_item_id: string | null;
};

export type Dnd5eCharacterSheet = {
  level: number;
  experience_current: number;
  experience_to_next_level: number;
  race: string;
  char_class: string;
  background: string;
  alignment: string;
  proficiency_bonus: number;
  armor_class: number;
  difficulty_class: number;
  speed_ft: number;
  initiative_bonus: number;
  stamina_current: number;
  stamina_maximum: number;
  is_dead: boolean;
  status_flags: string[];
  hit_dice: string;
  hit_points: Dnd5eHitPoints;
  ability_scores: Dnd5eAbilityScores;
  current_ability_scores: Dnd5eAbilityScores;
  ability_modifiers: Dnd5eAbilityModifiers;
  current_ability_modifiers: Dnd5eAbilityModifiers;
  saving_throws_proficient: string[];
  skills_proficient: string[];
  languages: string[];
  tool_proficiencies: string[];
  equipment: string[];
  equipment_slots: EquipmentSlots;
  backpack: InventoryData;
  buffs: RoleBuff[];
  features_traits: string[];
  spells: string[];
  spell_slots_max: Dnd5eSpellSlots;
  spell_slots_current: Dnd5eSpellSlots;
  notes: string;
};

export type RoleRelation = {
  target_role_id: string;
  relation_tag: string;
  note: string;
};

export type NpcDialogueEntry = {
  id: string;
  speaker: 'player' | 'npc';
  speaker_role_id: string;
  speaker_name: string;
  content: string;
  world_time_text: string;
  world_time: Record<string, string | number>;
  created_at: string;
};

export type NpcRoleCard = {
  role_id: string;
  name: string;
  zone_id: string | null;
  sub_zone_id: string | null;
  state: string;
  personality: string;
  speaking_style: string;
  appearance: string;
  background: string;
  cognition: string;
  alignment: string;
  profile: PlayerStaticData;
  relations: RoleRelation[];
  cognition_changes: string[];
  attitude_changes: string[];
  dialogue_logs: NpcDialogueEntry[];
  generated_at: string;
};

export type NpcGreetResponse = {
  ok: boolean;
  session_id: string;
  npc_role_id: string;
  greeting: string;
};

export type NpcChatResponse = {
  ok: boolean;
  session_id: string;
  npc_role_id: string;
  reply: string;
  time_spent_min: number;
  dialogue_logs: NpcDialogueEntry[];
};

export type ActionCheckResult = {
  ok: boolean;
  session_id: string;
  actor_role_id: string;
  action_type: 'attack' | 'check' | 'item_use';
  requires_check: boolean;
  ability_used: 'strength' | 'dexterity' | 'constitution' | 'intelligence' | 'wisdom' | 'charisma';
  ability_modifier: number;
  dc: number;
  dice_roll: number | null;
  total_score: number | null;
  success: boolean;
  critical: 'none' | 'critical_success' | 'critical_failure';
  time_spent_min: number;
  narrative: string;
  applied_effects: string[];
  relation_tag_suggestion: string | null;
};

export const defaultPlayerStaticData: PlayerStaticData = {
  player_id: 'player_001',
  name: '玩家',
  move_speed_mph: 4500,
  role_type: 'player',
  dnd5e_sheet: {
    level: 1,
    experience_current: 0,
    experience_to_next_level: 300,
    race: '',
    char_class: '',
    background: '',
    alignment: '',
    proficiency_bonus: 2,
    armor_class: 10,
    difficulty_class: 10,
    speed_ft: 30,
    initiative_bonus: 0,
    stamina_current: 10,
    stamina_maximum: 10,
    is_dead: false,
    status_flags: [],
    hit_dice: '1d8',
    hit_points: {
      current: 10,
      maximum: 10,
      temporary: 0,
    },
    ability_scores: {
      strength: 10,
      dexterity: 10,
      constitution: 10,
      intelligence: 10,
      wisdom: 10,
      charisma: 10,
    },
    current_ability_scores: {
      strength: 10,
      dexterity: 10,
      constitution: 10,
      intelligence: 10,
      wisdom: 10,
      charisma: 10,
    },
    ability_modifiers: {
      strength: 0,
      dexterity: 0,
      constitution: 0,
      intelligence: 0,
      wisdom: 0,
      charisma: 0,
    },
    current_ability_modifiers: {
      strength: 0,
      dexterity: 0,
      constitution: 0,
      intelligence: 0,
      wisdom: 0,
      charisma: 0,
    },
    saving_throws_proficient: [],
    skills_proficient: [],
    languages: [],
    tool_proficiencies: [],
    equipment: [],
    equipment_slots: {
      weapon_item_id: null,
      armor_item_id: null,
    },
    backpack: {
      gold: 0,
      items: [],
    },
    buffs: [],
    features_traits: [],
    spells: [],
    spell_slots_max: {
      level_1: 2,
      level_2: 0,
      level_3: 0,
      level_4: 0,
      level_5: 0,
      level_6: 0,
      level_7: 0,
      level_8: 0,
      level_9: 0,
    },
    spell_slots_current: {
      level_1: 2,
      level_2: 0,
      level_3: 0,
      level_4: 0,
      level_5: 0,
      level_6: 0,
      level_7: 0,
      level_8: 0,
      level_9: 0,
    },
    notes: '',
  },
};

export const defaultConfig: AppConfig = {
  version: '1.0.0',
  openai_api_key: 'sk-xxxx',
  model: 'gpt-4.1-mini',
  stream: true,
  temperature: 0.8,
  max_tokens: 1200,
  gm_prompt: '你是本次跑团的叙述者。请保持叙事一致、节奏紧凑，聚焦环境、人物与事件推进。',
  speech_time_per_50_tokens_min: 1,
  ui: {
    theme: 'dark',
  },
};
