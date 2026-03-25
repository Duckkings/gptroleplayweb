# gptroleplayweb

`gptroleplayweb` 是一个本地运行的跑团（Tabletop RPG）网页原型。这个项目本质上是一次“AI 滥用做游戏原型的测试”，也是对 AI 驱动游戏玩法和预生成内容的探索。它的目标不是做成完整商用产品，而是先把“主聊天推进剧情、公开回合完成结构化结算、地图驱动世界移动”这条闭环跑通。

## 这是一个什么游戏

- 本地优先的 RPG 原型，围绕“聊天推进剧情 + 系统结算”展开
- 玩家会在主聊天里直接进入公开回合，在同一条交互链里完成行动、台词、互动、对抗和结算
- 世界地图提供区块与子区块浏览、点击移动和时钟推进
- 玩家输入会在提交前经过统一校验，避免一次输入混入多个世界动作、结果断言或对其他角色的强制控制
- 适合用来验证叙事、规则和状态同步，而不是做纯文本聊天机器人

## 设计文档

如果你想了解规则设计和模块边界，先看这里：

- 设计总纲：[`docs/design/gamedesign/gamedesign.md`](docs/design/gamedesign/gamedesign.md)
- 公开回合总纲：[`docs/design/gamedesign/publicturndesign.md`](docs/design/gamedesign/publicturndesign.md)
- 公开回合交互：[`docs/design/gamedesign/publicturninteractiondesign.md`](docs/design/gamedesign/publicturninteractiondesign.md)
- 行动与检定：[`docs/design/gamedesign/actiondesign.md`](docs/design/gamedesign/actiondesign.md)
- 检定系统：[`docs/design/gamedesign/checksystemdesgin.md`](docs/design/gamedesign/checksystemdesgin.md)
- 世界地图：[`docs/design/gamedesign/worldmapdesign.md`](docs/design/gamedesign/worldmapdesign.md)
- 区块系统：[`docs/design/gamedesign/areadesign.md`](docs/design/gamedesign/areadesign.md)

技术实现和接口约束请继续看：

- 技术总索引：[`docs/technical/technical.md`](docs/technical/technical.md)
- 公开回合快照：[`docs/requirements/public-turn-capability-snapshot-2026-03-18.md`](docs/requirements/public-turn-capability-snapshot-2026-03-18.md)
- 玩家输入校验快照：[`docs/requirements/player-input-validation-capability-snapshot-2026-03-22.md`](docs/requirements/player-input-validation-capability-snapshot-2026-03-22.md)
- 当前功能快照：[`docs/technical/capability-snapshot-2026-03-25.md`](docs/technical/capability-snapshot-2026-03-25.md)

## 依赖

- Python 3.11 - 3.14
- Node.js / npm
- 可选：Docker 和 Docker Compose

### 后端依赖

- FastAPI
- Uvicorn
- Pydantic v2
- OpenAI Python SDK
- Google GenAI SDK
- itsdangerous
- Pillow

### 前端依赖

- React 19
- TypeScript
- Vite 7

## 启动方式

### 方式一：Windows 一键启动（`start-dev.bat` / `startdev`）

```bat
start-dev.bat
```

直接运行这个脚本即可，首次启动会自动准备依赖，不需要先手动执行 `pip install` 或 `npm install`。

这个脚本会自动：

- 检测 Python 3.11 - 3.14，找不到时也会尝试 `py -3`
- 创建或复用 `backend/.venv314`
- 安装后端和前端依赖
- 启动后端 `http://127.0.0.1:8000`
- 启动前端 `http://127.0.0.1:5173`
- 自动打开浏览器

### 方式二：Docker 开发模式

```bash
docker compose -f docker-compose.dev.yml up --build
```

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- 细节见：[`docs/docker-dev.md`](docs/docker-dev.md)

### 方式三：手动启动

1. 启动后端：

```powershell
cd backend
python -m venv .venv314
.\.venv314\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

2. 启动前端：

```powershell
cd frontend
npm install
npm run dev
```

3. 打开浏览器访问前端开发地址，然后到配置页完成 AI 接入。

## 常用开发命令

### 后端测试

```powershell
$env:PYTHONPATH='backend'
python -m unittest discover -s backend/tests
```

### 前端构建

```powershell
cd frontend
npm run build
```

## 说明

这是一个仅限本地运行的持续迭代原型。README 只描述当前已实现内容；更细的规则、边界和设计取舍，请优先看 `docs/design/` 和 `docs/technical/`。
