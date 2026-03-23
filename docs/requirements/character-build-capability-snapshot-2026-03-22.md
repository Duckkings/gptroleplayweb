# 玩家与随从构筑能力快照
更新时间: `2026-03-22`

## 当前已实现

- 新存档默认带 `character_build_state.player_status=uncreated`
- 前端新增 `CharacterBuildModal`，会在强制建角时阻塞主聊天
- Debug 面板新增 `创建玩家角色` / `创建随从队友`
- 玩家构筑完成后，若尚未看过提示且队伍为空，会弹一次首个随从提示

## 立绘链路

- 支持本地上传并用原生 canvas 做 `768x1344` 裁切
- 支持 AI 生图与参考图二次生成
- 上传图与 AI 图都会先保存为原始候选图
- 点击“确定立绘”后强制调用去背景
- 去背景成功后进入专用确认页
- 用户可从确认页返回立绘定制，保留 prompt、参考图、上传图和候选图
- 最终提交只接受 `final_portrait`

## 后端接口

- `GET /character-build/state`
- `GET /character-build/options`
- `GET /character-build/seeds/players`
- `GET /character-build/seeds/companions`
- `POST /character-build/suggest/*`
- `POST /character-build/media/upload`
- `POST /character-build/media/generate`
- `POST /character-build/media/remove-background`
- `POST /character-build/media/finalize`
- `POST /character-build/media/describe`
- `POST /character-build/player/complete`
- `POST /character-build/companion/complete`
- `POST /character-build/companion-offer`

## 存储

- save bundle 新增 `character_build_state.json`
- 临时立绘素材写入 `build-temp/portrait_assets/`
- 玩家留档写入 `player-builds/<archive_id>/`
- 随从留档画像写入 `retained-builds/<retained_id>/`

## 已验证

- `cd frontend && npm run build`
- `backend/.venv314/Scripts/python.exe -m unittest discover -s backend/tests`
