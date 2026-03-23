import { useEffect, useMemo, useRef, useState } from 'react';

import {
  completeCompanionBuild,
  completePlayerBuild,
  describeCharacterPortrait,
  finalizeCharacterPortrait,
  generateCharacterPortrait,
  getCharacterBuildAssetUrl,
  getCharacterBuildOptions,
  getCompanionBuildSeed,
  getCompanionBuildSeeds,
  getPlayerBuildSeed,
  getPlayerBuildSeeds,
  removeCharacterPortraitBackground,
  suggestCharacterBuildAbilities,
  suggestCharacterBuildBasicInfo,
  suggestCharacterBuildCompanionFlavor,
  suggestCharacterBuildLoadout,
  suggestCharacterBuildPortraitPrompt,
  uploadCharacterPortrait,
} from '../services/api';
import type {
  AppConfig,
  CharacterBuildAbilitySuggestResponse,
  CharacterBuildBasicInfo,
  CharacterBuildCompanionCompleteResponse,
  CharacterBuildCompanionFlavor,
  CharacterBuildCompanionFlavorSuggestResponse,
  CharacterBuildLoadoutSelection,
  CharacterBuildMediaGenerateResponse,
  CharacterBuildOptionsResponse,
  CharacterBuildPlayerCompleteResponse,
  CharacterBuildStateResponse,
  CompanionBuildSeedResponse,
  CompanionBuildSeedSummary,
  Dnd5eAbilityScores,
  PlayerBuildSeedResponse,
  PlayerBuildSeedSummary,
  PortraitAssetRef,
} from '../types/app';

type BuildMode = 'player' | 'companion';
type BuildSpecialization = 'warrior' | 'mage';
type BuildStep =
  | 'seed'
  | 'basic_info'
  | 'abilities'
  | 'specialization'
  | 'portrait_workspace'
  | 'portrait_review'
  | 'appearance'
  | 'loadout'
  | 'companion_flavor'
  | 'review';

type BuildResult = CharacterBuildPlayerCompleteResponse | CharacterBuildCompanionCompleteResponse;

type UploadEditorState = {
  dataUrl: string;
  fileName: string;
  naturalWidth: number;
  naturalHeight: number;
  zoom: number;
  offsetX: number;
  offsetY: number;
};

type Props = {
  open: boolean;
  forced?: boolean;
  mode: BuildMode;
  sessionId: string;
  config: AppConfig;
  initialState?: CharacterBuildStateResponse | null;
  onClose: () => void;
  onConfigRequired?: () => void;
  onCompleted: (result: BuildResult) => void | Promise<void>;
};

const PORTRAIT_WIDTH = 768;
const PORTRAIT_HEIGHT = 1344;
const PREVIEW_WIDTH = 192;
const PREVIEW_HEIGHT = 336;
const POINT_BUY_COSTS: Record<number, number> = { 8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9 };
const SPECIALIZATION_LABELS: Record<BuildSpecialization, string> = {
  warrior: 'Warrior',
  mage: 'Mage',
};
const STEP_LABELS: Record<BuildStep, string> = {
  seed: 'Seed',
  basic_info: 'Basic Info',
  abilities: '27-point buy',
  specialization: 'Specialization',
  portrait_workspace: 'Portrait',
  portrait_review: 'Review Portrait',
  appearance: 'Appearance',
  loadout: 'Loadout',
  companion_flavor: 'Companion Flavor',
  review: 'Review',
};

function defaultBasicInfo(): CharacterBuildBasicInfo {
  return {
    name: '',
    age: 18,
    race: '',
    height_cm: 170,
    body_type: '',
  };
}

function defaultFlavor(): CharacterBuildCompanionFlavor {
  return {
    personality: '',
    speaking_style: '',
    cognition: '',
    secret: '',
    likes: [],
  };
}

function defaultScores(specialization: BuildSpecialization): Dnd5eAbilityScores {
  if (specialization === 'mage') {
    return {
      strength: 8,
      dexterity: 14,
      constitution: 13,
      intelligence: 15,
      wisdom: 12,
      charisma: 10,
    };
  }
  return {
    strength: 15,
    dexterity: 13,
    constitution: 14,
    intelligence: 8,
    wisdom: 10,
    charisma: 12,
  };
}

function cloneScores(scores: Dnd5eAbilityScores): Dnd5eAbilityScores {
  return {
    strength: scores.strength,
    dexterity: scores.dexterity,
    constitution: scores.constitution,
    intelligence: scores.intelligence,
    wisdom: scores.wisdom,
    charisma: scores.charisma,
  };
}

function scoreEntries(scores: Dnd5eAbilityScores): Array<[keyof Dnd5eAbilityScores, number]> {
  return [
    ['strength', scores.strength],
    ['dexterity', scores.dexterity],
    ['constitution', scores.constitution],
    ['intelligence', scores.intelligence],
    ['wisdom', scores.wisdom],
    ['charisma', scores.charisma],
  ];
}

function pointBuyCost(scores: Dnd5eAbilityScores): number {
  return scoreEntries(scores).reduce((total, [, value]) => total + (POINT_BUY_COSTS[value] ?? 999), 0);
}

function normalizeAbilityScore(value: number): number {
  return Math.max(8, Math.min(15, Math.round(value || 8)));
}

function hasTextAiConfig(config: AppConfig): boolean {
  return Boolean(config.api_key?.trim() && config.model?.trim());
}

function activeBuildMediaProvider(config: AppConfig): 'openai' | 'deepseek' | 'gemini' {
  if (config.build_media.mode === 'explicit_provider') {
    return (config.build_media.explicit_provider ?? 'openai') as 'openai' | 'deepseek' | 'gemini';
  }
  return config.provider;
}

function mediaConfigSummary(config: AppConfig): string {
  const provider = activeBuildMediaProvider(config);
  if (provider === 'deepseek') {
    return 'Current media provider is DeepSeek and does not support portrait generation or background removal. Configure build media to use explicit OpenAI or Gemini.';
  }
  const providerConfig = config.build_media.provider_configs[provider];
  const apiKey = providerConfig.api_key?.trim() || (provider === config.provider ? config.api_key?.trim() : '');
  const generationModel =
    providerConfig.generation_model?.trim() ||
    providerConfig.background_removal_model?.trim() ||
    providerConfig.vision_model?.trim() ||
    (provider === config.provider ? config.model?.trim() : '');
  if (!apiKey) {
    return `${provider.toUpperCase()} build media API Key is empty.`;
  }
  if (!generationModel) {
    return `${provider.toUpperCase()} build media generation_model is empty.`;
  }
  return '';
}

function buildSteps(mode: BuildMode): BuildStep[] {
  if (mode === 'companion') {
    return ['seed', 'basic_info', 'abilities', 'specialization', 'portrait_workspace', 'portrait_review', 'appearance', 'loadout', 'companion_flavor', 'review'];
  }
  return ['seed', 'basic_info', 'abilities', 'specialization', 'portrait_workspace', 'portrait_review', 'appearance', 'loadout', 'review'];
}

function optionLabelFromIds(options: CharacterBuildOptionsResponse | null, ids: string[]): string[] {
  if (!options) return ids;
  const allOptions = [...options.spell_options, ...options.equipment_options, ...options.skill_options];
  const map = new Map(allOptions.map((item) => [item.option_id, item.label]));
  return ids.map((id) => map.get(id) ?? id);
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

function mergeAssets(existing: PortraitAssetRef[], incoming: PortraitAssetRef[]): PortraitAssetRef[] {
  const byId = new Map<string, PortraitAssetRef>();
  for (const asset of [...existing, ...incoming]) {
    byId.set(asset.asset_id, asset);
  }
  return Array.from(byId.values()).sort((left, right) => left.created_at.localeCompare(right.created_at));
}

function toggleLimitedSelection(current: string[], optionId: string, limit: number): string[] {
  if (current.includes(optionId)) {
    return current.filter((item) => item !== optionId);
  }
  if (limit <= 0 || current.length >= limit) return current;
  return [...current, optionId];
}

function drawCroppedPortrait(canvas: HTMLCanvasElement, image: HTMLImageElement, editor: UploadEditorState): void {
  canvas.width = PORTRAIT_WIDTH;
  canvas.height = PORTRAIT_HEIGHT;
  const context = canvas.getContext('2d');
  if (!context) return;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = '#08111e';
  context.fillRect(0, 0, canvas.width, canvas.height);
  const coverScale = Math.max(PORTRAIT_WIDTH / image.width, PORTRAIT_HEIGHT / image.height) * editor.zoom;
  const drawWidth = image.width * coverScale;
  const drawHeight = image.height * coverScale;
  const originX = (PORTRAIT_WIDTH - drawWidth) / 2 + editor.offsetX;
  const originY = (PORTRAIT_HEIGHT - drawHeight) / 2 + editor.offsetY;
  context.drawImage(image, originX, originY, drawWidth, drawHeight);
}

function drawPreview(canvas: HTMLCanvasElement, image: HTMLImageElement, editor: UploadEditorState): void {
  canvas.width = PREVIEW_WIDTH;
  canvas.height = PREVIEW_HEIGHT;
  const context = canvas.getContext('2d');
  if (!context) return;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = '#08111e';
  context.fillRect(0, 0, canvas.width, canvas.height);
  const scale = PREVIEW_WIDTH / PORTRAIT_WIDTH;
  const coverScale = Math.max(PORTRAIT_WIDTH / image.width, PORTRAIT_HEIGHT / image.height) * editor.zoom;
  const drawWidth = image.width * coverScale * scale;
  const drawHeight = image.height * coverScale * scale;
  const originX = ((PORTRAIT_WIDTH - image.width * coverScale) / 2 + editor.offsetX) * scale;
  const originY = ((PORTRAIT_HEIGHT - image.height * coverScale) / 2 + editor.offsetY) * scale;
  context.drawImage(image, originX, originY, drawWidth, drawHeight);
}

function likesTextToArray(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);
}

function likesArrayToText(value: string[]): string {
  return value.join('\n');
}

export function CharacterBuildModal({
  open,
  forced = false,
  mode,
  sessionId,
  config,
  initialState,
  onClose,
  onConfigRequired,
  onCompleted,
}: Props) {
  const steps = useMemo(() => buildSteps(mode), [mode]);
  const buildAiEnabled = hasTextAiConfig(config);
  const mediaProvider = activeBuildMediaProvider(config);
  const mediaBlockedReason = mediaConfigSummary(config);
  const mediaBlocked = Boolean(mediaBlockedReason);

  const [stepIndex, setStepIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [specialization, setSpecialization] = useState<BuildSpecialization>('warrior');
  const [basicInfo, setBasicInfo] = useState<CharacterBuildBasicInfo>(defaultBasicInfo());
  const [abilityScores, setAbilityScores] = useState<Dnd5eAbilityScores>(defaultScores('warrior'));
  const [portraitPrompt, setPortraitPrompt] = useState('');
  const [portraitPromptRequest, setPortraitPromptRequest] = useState('');
  const [basicInfoPrompt, setBasicInfoPrompt] = useState('');
  const [abilityPrompt, setAbilityPrompt] = useState('');
  const [loadoutPrompt, setLoadoutPrompt] = useState('');
  const [flavorPrompt, setFlavorPrompt] = useState('');
  const [appearance, setAppearance] = useState('');
  const [loadout, setLoadout] = useState<CharacterBuildLoadoutSelection>({
    spell_option_ids: [],
    equipment_option_ids: [],
    skill_option_ids: [],
  });
  const [flavor, setFlavor] = useState<CharacterBuildCompanionFlavor>(defaultFlavor());
  const [options, setOptions] = useState<CharacterBuildOptionsResponse | null>(null);
  const [playerSeeds, setPlayerSeeds] = useState<PlayerBuildSeedSummary[]>([]);
  const [companionSeeds, setCompanionSeeds] = useState<CompanionBuildSeedSummary[]>([]);
  const [referenceAssetId, setReferenceAssetId] = useState<string | null>(null);
  const [uploadedRawAssetId, setUploadedRawAssetId] = useState<string | null>(null);
  const [rawCandidates, setRawCandidates] = useState<PortraitAssetRef[]>([]);
  const [selectedRawAssetId, setSelectedRawAssetId] = useState<string | null>(null);
  const [bgRemovedAssetId, setBgRemovedAssetId] = useState<string | null>(null);
  const [finalizedAssetId, setFinalizedAssetId] = useState<string | null>(null);
  const [uploadEditor, setUploadEditor] = useState<UploadEditorState | null>(null);

  const step = steps[Math.min(stepIndex, steps.length - 1)];
  const previewCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const renderCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const uploadImageRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setStepIndex(0);
    setBusy(false);
    setError('');
    setSpecialization('warrior');
    setBasicInfo(defaultBasicInfo());
    setAbilityScores(defaultScores('warrior'));
    setPortraitPrompt('');
    setPortraitPromptRequest('');
    setBasicInfoPrompt('');
    setAbilityPrompt('');
    setLoadoutPrompt('');
    setFlavorPrompt('');
    setAppearance('');
    setLoadout({ spell_option_ids: [], equipment_option_ids: [], skill_option_ids: [] });
    setFlavor(defaultFlavor());
    setReferenceAssetId(null);
    setUploadedRawAssetId(null);
    setRawCandidates([]);
    setSelectedRawAssetId(null);
    setBgRemovedAssetId(null);
    setFinalizedAssetId(null);
    setUploadEditor(null);
    setPlayerSeeds([]);
    setCompanionSeeds([]);
  }, [open, mode, sessionId]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        if (mode === 'player') {
          const response = await getPlayerBuildSeeds();
          if (!cancelled) setPlayerSeeds(response.items);
        } else {
          const response = await getCompanionBuildSeeds();
          if (!cancelled) setCompanionSeeds(response.items);
        }
      } catch {
        if (!cancelled) {
          if (mode === 'player') setPlayerSeeds([]);
          else setCompanionSeeds([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, mode]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const next = await getCharacterBuildOptions(mode, specialization);
        if (cancelled) return;
        setOptions(next);
        setLoadout((current) => ({
          spell_option_ids: current.spell_option_ids.filter((item) => next.spell_options.some((option) => option.option_id === item)).slice(0, next.spell_pick_count),
          equipment_option_ids: current.equipment_option_ids.filter((item) => next.equipment_options.some((option) => option.option_id === item)).slice(0, next.equipment_pick_count),
          skill_option_ids: current.skill_option_ids.filter((item) => next.skill_options.some((option) => option.option_id === item)).slice(0, next.skill_pick_count),
        }));
      } catch (nextError) {
        if (!cancelled) {
          setOptions(null);
          setError(messageOf(nextError));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, mode, specialization]);

  useEffect(() => {
    if (!uploadEditor) {
      uploadImageRef.current = null;
      return;
    }
    const image = new Image();
    image.onload = () => {
      uploadImageRef.current = image;
      if (previewCanvasRef.current) {
        drawPreview(previewCanvasRef.current, image, uploadEditor);
      }
    };
    image.src = uploadEditor.dataUrl;
  }, [uploadEditor?.dataUrl]);

  useEffect(() => {
    if (!uploadEditor || !uploadImageRef.current || !previewCanvasRef.current) return;
    drawPreview(previewCanvasRef.current, uploadImageRef.current, uploadEditor);
  }, [uploadEditor]);

  const pointCost = useMemo(() => pointBuyCost(abilityScores), [abilityScores]);
  const currentRawAsset = useMemo(
    () => rawCandidates.find((asset) => asset.asset_id === selectedRawAssetId) ?? null,
    [rawCandidates, selectedRawAssetId],
  );
  const companionOfferPending = Boolean(initialState?.companion_offer_pending);
  const detailMessage = initialState?.media_capabilities.detail?.trim() ?? '';

  const goToStep = (target: BuildStep) => {
    const index = steps.indexOf(target);
    if (index >= 0) setStepIndex(index);
  };

  const nextStep = () => setStepIndex((current) => Math.min(current + 1, steps.length - 1));
  const previousStep = () => setStepIndex((current) => Math.max(current - 1, 0));

  const resetConfirmedPortrait = () => {
    setFinalizedAssetId(null);
  };

  const applyPlayerSeed = (response: PlayerBuildSeedResponse) => {
    const seed = response.seed;
    setBasicInfo(seed.basic_info);
    setSpecialization(seed.specialization);
    setAbilityScores(cloneScores(seed.player_static_data.dnd5e_sheet.ability_scores));
    setAppearance(seed.player_static_data.appearance ?? '');
    setFlavor(defaultFlavor());
    if (seed.player_static_data.portrait) {
      setRawCandidates([seed.player_static_data.portrait]);
      setFinalizedAssetId(seed.player_static_data.portrait.asset_id);
      setBgRemovedAssetId(seed.player_static_data.portrait.asset_id);
    }
  };

  const applyCompanionSeed = (response: CompanionBuildSeedResponse) => {
    const role = response.role;
    setBasicInfo({
      name: role.name,
      age: role.profile.age ?? 18,
      race: role.profile.dnd5e_sheet.race ?? '',
      height_cm: role.profile.height_cm ?? 170,
      body_type: role.profile.body_type ?? '',
    });
    setSpecialization(role.profile.dnd5e_sheet.char_class === '娉曞笀' ? 'mage' : 'warrior');
    setAbilityScores(cloneScores(role.profile.dnd5e_sheet.ability_scores));
    setAppearance(role.appearance ?? role.profile.appearance ?? '');
    setFlavor({
      personality: role.personality ?? '',
      speaking_style: role.speaking_style ?? '',
      cognition: role.cognition ?? '',
      secret: role.secret ?? '',
      likes: role.likes ?? [],
    });
    if (role.portrait) {
      setRawCandidates([role.portrait]);
      setFinalizedAssetId(role.portrait.asset_id);
      setBgRemovedAssetId(role.portrait.asset_id);
    }
  };

  const onUsePlayerSeed = async (archiveId: string) => {
    setBusy(true);
    setError('');
    try {
      const seed = await getPlayerBuildSeed(archiveId);
      applyPlayerSeed(seed);
      nextStep();
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onUseCompanionSeed = async (retainedId: string) => {
    setBusy(true);
    setError('');
    try {
      const seed = await getCompanionBuildSeed(retainedId);
      applyCompanionSeed(seed);
      nextStep();
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onStartBlank = () => {
    setError('');
    nextStep();
  };

  const onSuggestBasicInfo = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await suggestCharacterBuildBasicInfo({
        config,
        prompt: basicInfoPrompt,
        current: basicInfo,
        kind: mode,
      });
      setBasicInfo(response.basic_info);
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onSuggestAbilities = async () => {
    setBusy(true);
    setError('');
    try {
      const response: CharacterBuildAbilitySuggestResponse = await suggestCharacterBuildAbilities({
        config,
        prompt: abilityPrompt,
        current_scores: abilityScores,
        specialization,
      });
      setAbilityScores(cloneScores(response.ability_scores));
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onSuggestPortraitPrompt = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await suggestCharacterBuildPortraitPrompt({
        config,
        prompt: portraitPromptRequest,
        current_prompt: portraitPrompt,
        basic_info: basicInfo,
      });
      setPortraitPrompt(response.portrait_prompt);
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onSuggestLoadout = async () => {
    if (!options) return;
    setBusy(true);
    setError('');
    try {
      const response = await suggestCharacterBuildLoadout({
        config,
        prompt: loadoutPrompt,
        kind: mode,
        specialization,
        basic_info: basicInfo,
        appearance,
        available_spell_option_ids: options.spell_options.map((item) => item.option_id),
        available_equipment_option_ids: options.equipment_options.map((item) => item.option_id),
        available_skill_option_ids: options.skill_options.map((item) => item.option_id),
      });
      setLoadout({
        spell_option_ids: response.spell_option_ids.slice(0, options.spell_pick_count),
        equipment_option_ids: response.equipment_option_ids.slice(0, options.equipment_pick_count),
        skill_option_ids: response.skill_option_ids.slice(0, options.skill_pick_count),
      });
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onSuggestFlavor = async () => {
    setBusy(true);
    setError('');
    try {
      const response: CharacterBuildCompanionFlavorSuggestResponse = await suggestCharacterBuildCompanionFlavor({
        config,
        prompt: flavorPrompt,
        current: flavor,
        basic_info: basicInfo,
        appearance,
      });
      setFlavor(response.flavor);
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onLoadUploadFile = async (file: File) => {
    setError('');
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      if (!result) {
        setError('Failed to read image');
        return;
      }
      const image = new Image();
      image.onload = () => {
        setUploadEditor({
          dataUrl: result,
          fileName: file.name,
          naturalWidth: image.width,
          naturalHeight: image.height,
          zoom: 1,
          offsetX: 0,
          offsetY: 0,
        });
      };
      image.src = result;
    };
    reader.onerror = () => setError('Failed to read image');
    reader.readAsDataURL(file);
  };

  const onUploadCroppedPortrait = async () => {
    if (!uploadEditor || !uploadImageRef.current || !renderCanvasRef.current) return;
    setBusy(true);
    setError('');
    try {
      drawCroppedPortrait(renderCanvasRef.current, uploadImageRef.current, uploadEditor);
      const dataUrl = renderCanvasRef.current.toDataURL('image/png');
      const response = await uploadCharacterPortrait({
        data_base64: dataUrl,
        mime_type: 'image/png',
        file_name: uploadEditor.fileName,
      });
      const nextAsset = response.asset;
      setUploadedRawAssetId(nextAsset.asset_id);
      setReferenceAssetId(nextAsset.asset_id);
      setRawCandidates((current) => mergeAssets(current, [nextAsset]));
      setSelectedRawAssetId(nextAsset.asset_id);
      setBgRemovedAssetId(null);
      resetConfirmedPortrait();
      setUploadEditor(null);
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onGeneratePortraits = async () => {
    if (!portraitPrompt.trim()) {
      setError('Please enter a portrait prompt first');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response: CharacterBuildMediaGenerateResponse = await generateCharacterPortrait({
        config,
        prompt: portraitPrompt,
        basic_info: basicInfo,
        reference_asset_id: referenceAssetId,
      });
      if (response.assets.length === 0) {
        setError('No portraits were generated');
        return;
      }
      setRawCandidates((current) => mergeAssets(current, response.assets));
      setSelectedRawAssetId(response.assets[0].asset_id);
      setBgRemovedAssetId(null);
      resetConfirmedPortrait();
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onConfirmPortrait = async () => {
    if (!selectedRawAssetId) {
      setError('Please select a raw portrait first');
      return;
    }
    if (mediaBlocked) {
      setError(mediaBlockedReason);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await removeCharacterPortraitBackground({
        config,
        raw_asset_id: selectedRawAssetId,
      });
      setRawCandidates((current) => mergeAssets(current, [response.raw_asset, response.bg_removed_asset]));
      setBgRemovedAssetId(response.bg_removed_asset.asset_id);
      goToStep('portrait_review');
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onUseSelectedPortraitDirectly = async () => {
    if (!selectedRawAssetId) {
      setError('Please select a portrait first');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await finalizeCharacterPortrait({ asset_id: selectedRawAssetId });
      setRawCandidates((current) => mergeAssets(current, [response.asset]));
      setFinalizedAssetId(response.asset.asset_id);
      goToStep('appearance');
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onAcceptPortrait = async () => {
    if (!bgRemovedAssetId) {
      setError('Background-removed portrait is missing');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await finalizeCharacterPortrait({ asset_id: bgRemovedAssetId });
      setRawCandidates((current) => mergeAssets(current, [response.asset]));
      setFinalizedAssetId(response.asset.asset_id);
      goToStep('appearance');
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onDescribeAppearance = async () => {
    if (!finalizedAssetId) {
      setError('Please confirm a final portrait first');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await describeCharacterPortrait({
        config,
        asset_id: finalizedAssetId,
        basic_info: basicInfo,
      });
      setAppearance(response.description);
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const onSubmit = async () => {
    if (!finalizedAssetId) {
      setError('Please confirm a final portrait first');
      return;
    }
    if (!options) {
      setError('Build options are still loading');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const result =
        mode === 'player'
          ? await completePlayerBuild({
              session_id: sessionId,
              basic_info: basicInfo,
              specialization,
              ability_scores: abilityScores,
              final_portrait_asset_id: finalizedAssetId,
              appearance,
              loadout,
            })
          : await completeCompanionBuild({
              session_id: sessionId,
              basic_info: basicInfo,
              specialization,
              ability_scores: abilityScores,
              final_portrait_asset_id: finalizedAssetId,
              appearance,
              loadout,
              flavor,
            });
      await onCompleted(result);
    } catch (nextError) {
      setError(messageOf(nextError));
    } finally {
      setBusy(false);
    }
  };

  const validateCurrentStep = (): boolean => {
    if (step === 'basic_info') {
      if (!basicInfo.name.trim()) {
        setError('Please enter a name');
        return false;
      }
      if (!basicInfo.race.trim()) {
        setError('Please enter a race');
        return false;
      }
    }
    if (step === 'abilities' && pointCost > 27) {
      setError(`Point buy exceeds 27. Current total: ${pointCost}`);
      return false;
    }
    if (step === 'portrait_workspace') {
      if (!finalizedAssetId && !selectedRawAssetId) {
        setError('Please choose a portrait before continuing');
        return false;
      }
      if (finalizedAssetId) {
        goToStep('appearance');
        return false;
      }
      void onUseSelectedPortraitDirectly();
      return false;
    }
    if (step === 'appearance' && !appearance.trim()) {
      setError('Please confirm your appearance description');
      return false;
    }
    if (step === 'loadout' && options) {
      if (loadout.spell_option_ids.length !== options.spell_pick_count) {
        setError(`Choose ${options.spell_pick_count} spell option(s)`);
        return false;
      }
      if (loadout.equipment_option_ids.length !== options.equipment_pick_count) {
        setError(`Choose ${options.equipment_pick_count} equipment option(s)`);
        return false;
      }
      if (loadout.skill_option_ids.length !== options.skill_pick_count) {
        setError(`Choose ${options.skill_pick_count} skill option(s)`);
        return false;
      }
    }
    if (step === 'companion_flavor') {
      if (!flavor.personality.trim()) {
        setError('Please fill in companion personality');
        return false;
      }
      if (!flavor.speaking_style.trim()) {
        setError('Please fill in speaking style');
        return false;
      }
    }
    return true;
  };

  const onContinue = () => {
    setError('');
    if (!validateCurrentStep()) return;
    nextStep();
  };

  const renderSeedStep = () => (
    <section className="character-build-section">
      <div className="character-build-title-row">
        <div>
          <h3>{mode === 'player' ? 'Player Seed' : 'Companion Seed'}</h3>
          <p className="hint">You can reuse an archived seed or start from scratch.</p>
        </div>
        {mode === 'player' && forced && <span className="character-build-badge">Forced for new save</span>}
      </div>
      <div className="character-build-seed-actions">
        <button onClick={onStartBlank} disabled={busy}>
          Start from scratch
        </button>
      </div>
      <div className="character-build-seed-grid">
        {mode === 'player' &&
          playerSeeds.map((item) => (
            <article key={item.archive_id} className="character-build-seed-card">
              <div>
                <strong>{item.name}</strong>
                <p className="hint">{item.created_at || 'Unknown creation time'}</p>
              </div>
              {item.portrait && <img src={getCharacterBuildAssetUrl(item.portrait.asset_id)} alt={item.name} className="character-build-seed-preview" />}
              <button onClick={() => void onUsePlayerSeed(item.archive_id)} disabled={busy}>
                Use this seed
              </button>
            </article>
          ))}
        {mode === 'companion' &&
          companionSeeds.map((item) => (
            <article key={item.retained_id} className="character-build-seed-card">
              <div>
                <strong>{item.name}</strong>
                <p className="hint">{item.retained_at || 'Unknown retained time'}</p>
              </div>
              {item.portrait && <img src={getCharacterBuildAssetUrl(item.portrait.asset_id)} alt={item.name} className="character-build-seed-preview" />}
              <button onClick={() => void onUseCompanionSeed(item.retained_id)} disabled={busy}>
                Use this seed
              </button>
            </article>
          ))}
        {(mode === 'player' ? playerSeeds.length === 0 : companionSeeds.length === 0) && <p className="hint">No archived seeds are available yet.</p>}
      </div>
    </section>
  );

  const renderBasicInfoStep = () => (
    <section className="character-build-section">
      <h3>Basic Info</h3>
      <div className="character-build-grid">
        <label>
          <span>Name</span>
          <input
            type="text"
            value={basicInfo.name}
            onChange={(event) => setBasicInfo((current) => ({ ...current, name: event.target.value }))}
            placeholder={mode === 'player' ? 'Enter player name' : 'Enter companion name'}
          />
        </label>
        <label>
          <span>Age</span>
          <input
            type="number"
            min={0}
            max={999}
            value={basicInfo.age}
            onChange={(event) => setBasicInfo((current) => ({ ...current, age: Math.max(0, Number(event.target.value || 18)) }))}
          />
        </label>
        <label>
          <span>Race</span>
          <input
            type="text"
            value={basicInfo.race}
            onChange={(event) => setBasicInfo((current) => ({ ...current, race: event.target.value }))}
            placeholder="Enter race"
          />
        </label>
        <label>
          <span>Height (cm)</span>
          <input
            type="number"
            min={50}
            max={300}
            value={basicInfo.height_cm}
            onChange={(event) => setBasicInfo((current) => ({ ...current, height_cm: Math.max(50, Number(event.target.value || 170)) }))}
          />
        </label>
        <label className="character-build-grid-span-2">
          <span>Body type</span>
          <input
            type="text"
            value={basicInfo.body_type}
            onChange={(event) => setBasicInfo((current) => ({ ...current, body_type: event.target.value }))}
            placeholder="Example: compact / tall / athletic"
          />
        </label>
      </div>
      <div className="character-build-tag-row">
        {(options?.recommended_races ?? []).map((item) => (
          <button key={item} type="button" className="ghost-button" onClick={() => setBasicInfo((current) => ({ ...current, race: item }))}>
            {item}
          </button>
        ))}
        {(options?.body_type_suggestions ?? []).map((item) => (
          <button key={item} type="button" className="ghost-button" onClick={() => setBasicInfo((current) => ({ ...current, body_type: item }))}>
            {item}
          </button>
        ))}
      </div>
      <div className="character-build-ai-box">
        <textarea value={basicInfoPrompt} onChange={(event) => setBasicInfoPrompt(event.target.value)} placeholder="Describe the character basics you want AI to fill in." />
        <button onClick={() => void onSuggestBasicInfo()} disabled={busy || !buildAiEnabled}>
          AI fill basics
        </button>
      </div>
    </section>
  );

  const renderAbilitiesStep = () => (
    <section className="character-build-section">
      <div className="character-build-title-row">
        <div>
          <h3>27-point buy</h3>
          <p className={`hint ${pointCost > 27 ? 'error' : ''}`}>Spent {pointCost} / 27</p>
        </div>
        <button onClick={() => setAbilityScores(defaultScores(specialization))} disabled={busy}>
          Reset to recommended
        </button>
      </div>
      <div className="character-build-grid">
        {scoreEntries(abilityScores).map(([key, value]) => (
          <label key={key}>
            <span>{key.toUpperCase()}</span>
            <input
              type="number"
              min={8}
              max={15}
              value={value}
              onChange={(event) =>
                setAbilityScores((current) => ({
                  ...current,
                  [key]: normalizeAbilityScore(Number(event.target.value)),
                }))
              }
            />
          </label>
        ))}
      </div>
      <p className="hint">Cost table: 8=0, 9=1, 10=2, 11=3, 12=4, 13=5, 14=7, 15=9.</p>
      <div className="character-build-ai-box">
        <textarea value={abilityPrompt} onChange={(event) => setAbilityPrompt(event.target.value)} placeholder="Example: mobile mage, keep perception reasonable." />
        <button onClick={() => void onSuggestAbilities()} disabled={busy || !buildAiEnabled}>
          AI suggest scores
        </button>
      </div>
    </section>
  );

  const renderSpecializationStep = () => (
    <section className="character-build-section">
      <h3>Specialization</h3>
      <div className="character-build-choice-row">
        <button type="button" className={specialization === 'warrior' ? 'selected' : ''} onClick={() => setSpecialization('warrior')}>
          Warrior
        </button>
        <button type="button" className={specialization === 'mage' ? 'selected' : ''} onClick={() => setSpecialization('mage')}>
          Mage
        </button>
      </div>
      <p className="hint">
        Current path: {SPECIALIZATION_LABELS[specialization]}
        {options ? ` | Spells ${options.spell_pick_count} / Equipment ${options.equipment_pick_count} / Skills ${options.skill_pick_count}` : ''}
      </p>
    </section>
  );

  const renderPortraitWorkspaceStep = () => (
    <section className="character-build-section">
      <h3>Portrait Workspace</h3>
      {(mediaBlocked || detailMessage) && (
        <div className="character-build-warning">
          <p>{mediaBlockedReason || detailMessage}</p>
          {onConfigRequired && (
            <button onClick={onConfigRequired} type="button">
              Open build media config
            </button>
          )}
        </div>
      )}
      {finalizedAssetId && (
        <div className="character-build-current-portrait">
          <p className="hint">Current confirmed portrait</p>
          <img src={getCharacterBuildAssetUrl(finalizedAssetId)} alt="confirmed portrait" className="character-build-review-image" />
          <button type="button" onClick={() => goToStep('appearance')}>
            Reuse current confirmed portrait
          </button>
        </div>
      )}
      <div className="character-build-ai-box">
        <textarea
          value={portraitPrompt}
          onChange={(event) => setPortraitPrompt(event.target.value)}
          placeholder="Describe the portrait you want, for example: full body, standing, traveling mage, red hair, long staff."
        />
        <div className="character-build-inline-actions">
          <button onClick={() => void onGeneratePortraits()} disabled={busy || mediaBlocked}>
            Generate portraits
          </button>
          <button onClick={() => void onSuggestPortraitPrompt()} disabled={busy || !buildAiEnabled}>
            AI improve prompt
          </button>
        </div>
        <textarea
          value={portraitPromptRequest}
          onChange={(event) => setPortraitPromptRequest(event.target.value)}
          placeholder="Tell AI which style, clothes, mood, or weapon details to emphasize."
        />
      </div>
      <div className="character-build-upload-box">
        <div className="character-build-title-row">
          <strong>Upload and crop locally</strong>
          <input type="file" accept="image/*" onChange={(event) => event.target.files?.[0] && void onLoadUploadFile(event.target.files[0])} />
        </div>
        {uploadEditor && (
          <div className="character-build-crop-grid">
            <canvas ref={previewCanvasRef} className="character-build-crop-preview" />
            <div className="character-build-grid">
              <label>
                <span>Zoom</span>
                <input
                  type="range"
                  min={1}
                  max={2.5}
                  step={0.01}
                  value={uploadEditor.zoom}
                  onChange={(event) => setUploadEditor((current) => (current ? { ...current, zoom: Number(event.target.value) } : current))}
                />
              </label>
              <label>
                <span>Horizontal offset</span>
                <input
                  type="range"
                  min={-400}
                  max={400}
                  step={1}
                  value={uploadEditor.offsetX}
                  onChange={(event) => setUploadEditor((current) => (current ? { ...current, offsetX: Number(event.target.value) } : current))}
                />
              </label>
              <label>
                <span>Vertical offset</span>
                <input
                  type="range"
                  min={-600}
                  max={600}
                  step={1}
                  value={uploadEditor.offsetY}
                  onChange={(event) => setUploadEditor((current) => (current ? { ...current, offsetY: Number(event.target.value) } : current))}
                />
              </label>
              <p className="hint">
                Source image: {uploadEditor.naturalWidth} x {uploadEditor.naturalHeight}
              </p>
              <div className="character-build-inline-actions">
                <button type="button" onClick={() => void onUploadCroppedPortrait()} disabled={busy}>
                  Upload cropped image
                </button>
                <button type="button" onClick={() => setUploadEditor(null)} disabled={busy}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="character-build-title-row">
        <strong>Raw portrait candidates</strong>
        <p className="hint">Uploaded and generated images stay here. Returning from review does not lose them.</p>
      </div>
      <div className="character-build-asset-grid">
        {rawCandidates.map((asset) => (
          <article key={asset.asset_id} className={`character-build-asset-card ${selectedRawAssetId === asset.asset_id ? 'selected' : ''}`}>
            <img src={getCharacterBuildAssetUrl(asset.asset_id)} alt={asset.asset_id} />
            <p className="hint">{asset.variant_kind}</p>
            <div className="character-build-inline-actions">
              {asset.variant_kind !== 'bg_removed' && asset.variant_kind !== 'final_portrait' && (
                <button
                  type="button"
                  onClick={() => {
                    setSelectedRawAssetId(asset.asset_id);
                    setReferenceAssetId((current) => current ?? asset.asset_id);
                    resetConfirmedPortrait();
                  }}
                >
                  Select as source
                </button>
              )}
              <button type="button" onClick={() => setReferenceAssetId(asset.asset_id)}>
                Use as reference
              </button>
            </div>
          </article>
        ))}
        {rawCandidates.length === 0 && <p className="hint">No portrait assets yet.</p>}
      </div>
      <p className="hint">
        Current media provider: {mediaProvider}
        {referenceAssetId ? ` | Reference: ${referenceAssetId}` : ''}
        {uploadedRawAssetId ? ` | Uploaded: ${uploadedRawAssetId}` : ''}
      </p>
      {currentRawAsset && <p className="hint">Current selected source: {currentRawAsset.asset_id}</p>}
      <div className="character-build-inline-actions">
        <button onClick={() => void onConfirmPortrait()} disabled={busy || !selectedRawAssetId || mediaBlocked}>
          Remove background first
        </button>
      </div>
      <p className="hint">The main confirm button below will continue with the selected original image directly. Background removal is optional.</p>
      <canvas ref={renderCanvasRef} className="character-build-hidden-canvas" />
    </section>
  );

  const renderPortraitReviewStep = () => (
    <section className="character-build-section">
      <h3>Portrait Review</h3>
      <p className="hint">This shows the background-removed PNG preview. Return to the workspace if you want a different result.</p>
      {bgRemovedAssetId ? (
        <div className="character-build-review-stage">
          <div className="character-build-checkerboard">
            <img src={getCharacterBuildAssetUrl(bgRemovedAssetId)} alt="background removed portrait" className="character-build-review-image" />
          </div>
        </div>
      ) : (
        <p className="hint">No background-removed result yet.</p>
      )}
      <div className="actions">
        <button onClick={() => goToStep('portrait_workspace')} disabled={busy}>
          Back to workspace
        </button>
        <button onClick={() => void onAcceptPortrait()} disabled={busy || !bgRemovedAssetId}>
          Use this portrait
        </button>
      </div>
    </section>
  );

  const renderAppearanceStep = () => (
    <section className="character-build-section">
      <h3>Appearance</h3>
      {finalizedAssetId && <img src={getCharacterBuildAssetUrl(finalizedAssetId)} alt="final portrait" className="character-build-review-image" />}
      <textarea value={appearance} onChange={(event) => setAppearance(event.target.value)} placeholder="Describe the character appearance. This will be written to the character card." />
      <div className="character-build-inline-actions">
        <button onClick={() => void onDescribeAppearance()} disabled={busy || mediaBlocked || !finalizedAssetId}>
          Describe from image
        </button>
        <button onClick={() => goToStep('portrait_workspace')} disabled={busy}>
          Back to portrait workspace
        </button>
      </div>
    </section>
  );

  const renderLoadoutStep = () => (
    <section className="character-build-section">
      <h3>Starting spells / equipment / skills</h3>
      {!options ? (
        <p className="hint">Loading options...</p>
      ) : (
        <>
          <div className="character-build-loadout-section">
            <div className="character-build-title-row">
              <strong>Spells</strong>
              <span className="hint">
                {loadout.spell_option_ids.length}/{options.spell_pick_count}
              </span>
            </div>
            <div className="character-build-option-list">
              {options.spell_options.map((item) => (
                <label key={item.option_id} className={`character-build-option ${loadout.spell_option_ids.includes(item.option_id) ? 'selected' : ''}`}>
                  <input
                    type="checkbox"
                    checked={loadout.spell_option_ids.includes(item.option_id)}
                    onChange={() =>
                      setLoadout((current) => ({
                        ...current,
                        spell_option_ids: toggleLimitedSelection(current.spell_option_ids, item.option_id, options.spell_pick_count),
                      }))
                    }
                  />
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.description}</small>
                  </span>
                </label>
              ))}
            </div>
          </div>
          <div className="character-build-loadout-section">
            <div className="character-build-title-row">
              <strong>Equipment</strong>
              <span className="hint">
                {loadout.equipment_option_ids.length}/{options.equipment_pick_count}
              </span>
            </div>
            <div className="character-build-option-list">
              {options.equipment_options.map((item) => (
                <label key={item.option_id} className={`character-build-option ${loadout.equipment_option_ids.includes(item.option_id) ? 'selected' : ''}`}>
                  <input
                    type="checkbox"
                    checked={loadout.equipment_option_ids.includes(item.option_id)}
                    onChange={() =>
                      setLoadout((current) => ({
                        ...current,
                        equipment_option_ids: toggleLimitedSelection(current.equipment_option_ids, item.option_id, options.equipment_pick_count),
                      }))
                    }
                  />
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.description}</small>
                  </span>
                </label>
              ))}
            </div>
          </div>
          {options.skill_pick_count > 0 && (
            <div className="character-build-loadout-section">
              <div className="character-build-title-row">
                <strong>Skills</strong>
                <span className="hint">
                  {loadout.skill_option_ids.length}/{options.skill_pick_count}
                </span>
              </div>
              <div className="character-build-option-list">
                {options.skill_options.map((item) => (
                  <label key={item.option_id} className={`character-build-option ${loadout.skill_option_ids.includes(item.option_id) ? 'selected' : ''}`}>
                    <input
                      type="checkbox"
                      checked={loadout.skill_option_ids.includes(item.option_id)}
                      onChange={() =>
                        setLoadout((current) => ({
                          ...current,
                          skill_option_ids: toggleLimitedSelection(current.skill_option_ids, item.option_id, options.skill_pick_count),
                        }))
                      }
                    />
                    <span>
                      <strong>{item.label}</strong>
                      <small>{item.description}</small>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}
          <div className="character-build-loadout-section">
            <strong>Granted items</strong>
            <p className="hint">Default armor: {options.granted_armor?.label ?? 'None'} | Extra items: {options.granted_items.map((item) => item.label).join(' / ') || 'None'}</p>
          </div>
        </>
      )}
      <div className="character-build-ai-box">
        <textarea value={loadoutPrompt} onChange={(event) => setLoadoutPrompt(event.target.value)} placeholder="Example: prefer fire spells, a safe sidearm, and practical combat skills." />
        <button onClick={() => void onSuggestLoadout()} disabled={busy || !buildAiEnabled || !options}>
          AI suggest loadout
        </button>
      </div>
    </section>
  );

  const renderFlavorStep = () => (
    <section className="character-build-section">
      <h3>Companion Personality</h3>
      <div className="character-build-grid">
        <label className="character-build-grid-span-2">
          <span>Personality</span>
          <textarea value={flavor.personality} onChange={(event) => setFlavor((current) => ({ ...current, personality: event.target.value }))} />
        </label>
        <label>
          <span>Speaking style</span>
          <textarea value={flavor.speaking_style} onChange={(event) => setFlavor((current) => ({ ...current, speaking_style: event.target.value }))} />
        </label>
        <label>
          <span>Cognition</span>
          <textarea value={flavor.cognition} onChange={(event) => setFlavor((current) => ({ ...current, cognition: event.target.value }))} />
        </label>
        <label>
          <span>Secret</span>
          <textarea value={flavor.secret} onChange={(event) => setFlavor((current) => ({ ...current, secret: event.target.value }))} />
        </label>
        <label>
          <span>Likes</span>
          <textarea
            value={likesArrayToText(flavor.likes)}
            onChange={(event) => setFlavor((current) => ({ ...current, likes: likesTextToArray(event.target.value) }))}
            placeholder="One item per line"
          />
        </label>
      </div>
      <div className="character-build-ai-box">
        <textarea value={flavorPrompt} onChange={(event) => setFlavorPrompt(event.target.value)} placeholder="Example: loyal but sharp-tongued, observant, and emotionally reserved." />
        <button onClick={() => void onSuggestFlavor()} disabled={busy || !buildAiEnabled}>
          AI suggest flavor
        </button>
      </div>
    </section>
  );

  const renderReviewStep = () => (
    <section className="character-build-section">
      <div className="character-build-title-row">
        <div>
          <h3>Review</h3>
          <p className="hint">{mode === 'player' ? 'Submitting will archive the player build.' : 'Submitting will create the companion and write it to retained storage.'}</p>
        </div>
        {companionOfferPending && mode === 'companion' && <span className="character-build-badge">Initial companion prompt</span>}
      </div>
      <div className="character-build-summary-grid">
        {finalizedAssetId && <img src={getCharacterBuildAssetUrl(finalizedAssetId)} alt="final portrait" className="character-build-review-image" />}
        <div>
          <p>
            <strong>{basicInfo.name || 'Unnamed'}</strong> / {basicInfo.race || 'Unknown race'} / {SPECIALIZATION_LABELS[specialization]}
          </p>
          <p className="hint">
            Age {basicInfo.age} / Height {basicInfo.height_cm}cm / Body type {basicInfo.body_type || 'Not set'}
          </p>
          <p>{appearance || 'Appearance description not set'}</p>
          <p className="hint">Spells: {optionLabelFromIds(options, loadout.spell_option_ids).join(' / ') || 'None'}</p>
          <p className="hint">Equipment: {optionLabelFromIds(options, loadout.equipment_option_ids).join(' / ') || 'None'}</p>
          {loadout.skill_option_ids.length > 0 && <p className="hint">Skills: {optionLabelFromIds(options, loadout.skill_option_ids).join(' / ')}</p>}
          {mode === 'companion' && (
            <>
              <p className="hint">Personality: {flavor.personality || 'Not set'}</p>
              <p className="hint">Speaking style: {flavor.speaking_style || 'Not set'}</p>
            </>
          )}
        </div>
      </div>
    </section>
  );

  if (!open) return null;

  return (
    <div className="modal-mask">
      <div className="modal-card modal-wide character-build-card" role="dialog" aria-modal="true">
        <div className="character-build-title-row">
          <div>
            <h3>{mode === 'player' ? 'Player Build' : 'Companion Build'}</h3>
            <p className="hint">Step {stepIndex + 1} / {steps.length}</p>
          </div>
          {!forced && (
            <button type="button" onClick={onClose} disabled={busy}>
              Close
            </button>
          )}
        </div>

        <div className="character-build-progress">
          {steps.map((item, index) => (
            <span key={item} className={index === stepIndex ? 'active' : index < stepIndex ? 'done' : ''}>
              {STEP_LABELS[item]}
            </span>
          ))}
        </div>

        {step === 'seed' && renderSeedStep()}
        {step === 'basic_info' && renderBasicInfoStep()}
        {step === 'abilities' && renderAbilitiesStep()}
        {step === 'specialization' && renderSpecializationStep()}
        {step === 'portrait_workspace' && renderPortraitWorkspaceStep()}
        {step === 'portrait_review' && renderPortraitReviewStep()}
        {step === 'appearance' && renderAppearanceStep()}
        {step === 'loadout' && renderLoadoutStep()}
        {step === 'companion_flavor' && renderFlavorStep()}
        {step === 'review' && renderReviewStep()}

        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button onClick={step === 'seed' ? onClose : previousStep} disabled={busy || (forced && step === 'seed')}>
            {step === 'seed' ? 'Cancel' : 'Back'}
          </button>
          {step !== 'portrait_review' && step !== 'review' && (
            <button onClick={onContinue} disabled={busy}>
              {step === 'portrait_workspace' ? 'Use Current Portrait' : 'Next'}
            </button>
          )}
          {step === 'review' && (
            <button onClick={() => void onSubmit()} disabled={busy}>
              {busy ? 'Submitting...' : mode === 'player' ? 'Complete Player Build' : 'Complete Companion Build'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
