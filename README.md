# gptroleplayweb

`gptroleplayweb` 是一个本地运行的跑团网页原型：后端负责世界状态、存档、任务/命运/遭遇/角色规则与 AI 编排，前端提供聊天、配置、地图、日志、角色与调试界面。

## 当前已实现功能

### 1. AI 配置与接入
- 结构化配置页，替代原始 JSON 文本框
- 支持 `OpenAI / DeepSeek` 服务切换
- 支持填写 `API Key`
- 支持可选 `Base URL override`
- 支持从服务端拉取模型列表
- 模型列表拉取失败时支持手动输入模型名
- 根据所选模型动态展示可配置参数
- 后端统一处理模型能力差异，例如 `gpt-5` 使用 `max_completion_tokens`
- 配置校验支持旧格式自动迁移并保存为新格式

### 2. 聊天与叙事
- 主叙事聊天
- NPC 单聊
- 非流式聊天 + SSE 流式聊天
- 停止生成
- 调用后端工具完成世界状态读取/写入后再继续叙事
- 聊天内容与游戏状态联动推进

### 3. 世界、地图与区域
- 世界地图区块生成
- 地图渲染
- 区域 / 子区域移动
- 世界时钟推进
- 区域交互发现与执行入口
- 移动、交互、叙事反馈写入日志

### 4. 命运、任务、遭遇
- 命运线生成、重生成、阶段推进与查看
- 普通任务生成、接受、拒绝、追踪、评估
- 命运任务 `accept_only`
- 遭遇生成、排队、展示、行动、脱离、回归、历史查看
- 阻塞式弹窗优先级已实现：命运/任务优先于遭遇
- 遭遇全文可在日志/历史中查看

### 5. 角色、背包与队伍
- 玩家静态/运行时数据编辑
- 背包查看、装备、卸下、物品交互
- Buff / 物品 / 技能 / 法术 / 资源调整
- NPC 角色池浏览与详情查看
- 队伍邀请、离队、调试队友生成
- 队伍聊天与队友反应
- 队友背包/资料查看

### 6. 调试与回归辅助
- Debug 面板集中入口
- 存档路径 / 配置路径选择
- 导入、清空、切换当前存档
- 命运 / 任务 / 遭遇 / 队伍等调试按钮
- 一致性状态查看与执行
- 游戏日志查看
- Token 使用统计

## 项目结构

- `backend/`: FastAPI 后端、业务服务、数据模型、存储逻辑、测试
- `frontend/`: React + TypeScript 前端
- `shared/`: 共享 schema
- `docs/`: 设计、需求与技术文档
- `start-dev.bat`: Windows 下一键启动前后端

## 快速开始

### 方式一：一键启动（Windows 本机）
```bat
start-dev.bat
```

### 方式二：Docker 开发模式（推荐：不想装 Python）
```bash
docker compose -f docker-compose.dev.yml up --build
```

更多说明见：`docs/docker-dev.md`

### 方式三：手动启动

1. 启动后端：
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

2. 启动前端：
```powershell
cd frontend
npm install
npm run dev
```

3. 打开浏览器访问前端开发地址，进入配置页：
- 选择 `OpenAI` 或 `DeepSeek`
- 填入 `API Key`
- 点击“获取模型”或手动输入模型名
- 根据模型能力填写参数
- 校验并进入聊天

## 常用开发命令

### 前端
```powershell
cd frontend
npm run dev
npm run build
```

### 后端
```powershell
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 后端测试
```powershell
cd backend
python -m unittest discover -s tests -p "test_*.py"
```

## 当前技术说明

- 后端：FastAPI + Pydantic + OpenAI Python SDK
- 前端：React 19 + TypeScript + Vite
- 存储：本地 JSON / bundle 分片存档
- AI 访问：统一 provider/profile 适配层，按模型过滤参数

## 文档入口

- 架构与总体技术说明：`docs/technical/mvp-architecture.md`
- 技术总索引：`docs/technical/technical.md`
- 当前功能需求背景：`docs/requirements/pending-2026-03-01.md`

## 说明

当前仓库是持续迭代中的本地原型，不是最终产品版。README 以“当前已落地功能”为准；更细的系统约束和设计取舍，请看 `docs/` 下对应文档。
