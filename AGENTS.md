# AGENTS.md

## Project Overview

`gptroleplayweb` is a locally-hosted tabletop RPG (跑团) web prototype. The backend manages world state, save games, quest/fate/encounter/character rules, and AI orchestration. The frontend provides chat, configuration, map, logs, character, and debugging interfaces.

This is a **local-only prototype** (not a production product) under continuous iteration. Always refer to "currently implemented features" as the source of truth; for detailed system constraints and design trade-offs, see the `docs/` directory.

## Technology Stack

### Backend
- **Framework**: FastAPI + Uvicorn
- **Language**: Python 3.11 - 3.14 (recommended 3.12 or 3.14)
- **Data Validation**: Pydantic v2
- **AI SDKs**: OpenAI Python SDK, Google GenAI SDK
- **Authentication**: `itsdangerous` for signed session cookies
- **CORS**: Configured for local development (ports 5173)

### Frontend
- **Framework**: React 19 + TypeScript
- **Build Tool**: Vite 7
- **Linting**: ESLint 9 with TypeScript ESLint, React Hooks, React Refresh
- **Package Manager**: npm

### Storage
- **Config**: Local JSON files (`config.json`)
- **Saves**: Bundle-based sharded JSON archives (world state, player data, quests, encounters, etc.)
- **Multi-user**: Data isolated per user under `data/users/<username>/`

### AI Integration
- **Supported Providers**: OpenAI, DeepSeek, Gemini
- **Streaming**: Server-Sent Events (SSE) for real-time narrative
- **Non-streaming**: Standard JSON responses

## Project Structure

```
gptroleplayweb/
├── backend/                  # FastAPI backend
│   ├── app/
│   │   ├── main.py          # Application entry point
│   │   ├── api/             # API routes
│   │   │   ├── routes.py    # Main API endpoints
│   │   │   └── auth_routes.py  # Authentication endpoints
│   │   ├── core/            # Core utilities
│   │   │   ├── auth.py      # Session management
│   │   │   ├── storage.py   # File I/O operations
│   │   │   ├── prompt_table.py  # AI prompt registry
│   │   │   └── token_usage.py   # Token tracking
│   │   ├── models/          # Pydantic schemas
│   │   │   └── schemas.py   # Data models (config, saves, etc.)
│   │   └── services/        # Business logic
│   │       ├── world_service.py      # World state management
│   │       ├── chat_service.py       # Main chat orchestration
│   │       ├── stream_chat_service.py # SSE streaming
│   │       ├── fate_service.py       # Fate/destiny system
│   │       ├── quest_service.py      # Quest management
│   │       ├── encounter_service.py  # Encounter system
│   │       ├── team_service.py       # Party/team management
│   │       ├── battle_service.py     # Combat system
│   │       └── ...
│   ├── tests/               # Unit tests
│   ├── requirements.txt     # Python dependencies
│   └── Dockerfile           # Backend container
├── frontend/                # React + TypeScript frontend
│   ├── src/
│   │   ├── App.tsx          # Main application component
│   │   ├── main.tsx         # Entry point
│   │   ├── components/      # React components
│   │   │   ├── DebugPanel.tsx
│   │   │   ├── QuestModal.tsx
│   │   │   ├── EncounterModal.tsx
│   │   │   ├── FatePanel.tsx
│   │   │   └── ...
│   │   ├── services/        # API clients
│   │   │   └── api.ts
│   │   └── types/           # TypeScript types
│   │       └── app.ts
│   ├── package.json         # npm dependencies
│   ├── vite.config.ts       # Vite configuration
│   ├── tsconfig.json        # TypeScript configuration
│   ├── eslint.config.js     # ESLint configuration
│   └── Dockerfile           # Frontend container
├── data/                    # Runtime data
│   ├── ai-prompts.csv       # AI prompt templates
│   ├── config.json          # Global configuration
│   ├── current-save.json    # Active save file (bundle format)
│   ├── users/               # Per-user data
│   └── storage/paths.json   # Path configuration
├── shared/                  # Shared schemas
│   └── schemas/
│       └── config.schema.json
├── docs/                    # Documentation
│   ├── design/gamedesign/   # Game design documents
│   ├── technical/           # Technical specifications
│   └── requirements/        # Feature requirements
├── docker-compose.dev.yml   # Docker development setup
├── start-dev.bat           # Windows one-click launcher
└── AGENTS.md               # This file
```

## Build and Development Commands

### Quick Start (Windows)
```bat
start-dev.bat
```
This script:
- Auto-detects Python (3.11-3.14) or `py -3`
- Creates `backend/.venv314` if missing
- Installs backend and frontend dependencies (first run)
- Starts backend at `127.0.0.1:8000` and frontend at `127.0.0.1:5173`
- Opens browser automatically

### Docker Development
```bash
docker compose -f docker-compose.dev.yml up --build
```
- Frontend: http://localhost:5173
- Backend: http://localhost:8000

### Manual Backend Startup
```powershell
cd backend
python -m venv .venv314
.\.venv314\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Manual Frontend Startup
```powershell
cd frontend
npm install
npm run dev
```

### Frontend Build
```powershell
cd frontend
npm run build
```

## Testing

### Backend Tests
```powershell
$env:PYTHONPATH='backend'
python -m unittest discover -s backend/tests
```

Test files are located in `backend/tests/` and follow the `test_*.py` naming convention:
- `test_config_models.py` - Configuration validation
- `test_chat_route_scene_rendering.py` - Chat scene rendering
- `test_quest_fate_encounter.py` - Quest/fate/encounter systems
- `test_encounter_service.py` - Encounter mechanics
- `test_team_service.py` - Team management
- `test_battle_service.py` - Combat system
- And more...

### Frontend Build Verification
```powershell
cd frontend
npm run build
```

## Code Style Guidelines

### Python (Backend)
- Follow PEP 8 conventions
- Use type hints where practical
- Use Pydantic v2 for data validation
- Services follow single-responsibility pattern
- API routes in `api/` directory, business logic in `services/` directory

### TypeScript (Frontend)
- ESLint configuration in `eslint.config.js`
- React Hooks rules enforced
- React Refresh for hot reloading
- TypeScript strict mode recommended
- Components use `.tsx` extension

### Documentation Rules
- When `schemas.py` or `frontend/src/types/app.ts` changes, update corresponding technical docs
- When adding `scene_events`, tool schemas, API routes, or Save bundle shards, update:
  - `docs/technical/gameplay-core-technical.md`
  - `docs/technical/ai-tool-protocol.md`
  - `docs/technical/save-technical.md`
- After feature completion, write a capability snapshot document

## Key Architecture Patterns

### Modal Priority System
All modals block the chat interface. Priority order:
1. Fate/Quest modals (highest)
2. Encounter modal
3. Main chat (lowest)

### Quest Types
- **Fate Quests**: `accept_only` - players cannot reject
- **Normal Quests**: `accept/reject` with narrative output in chat

### Save System
- Uses bundle format with JSON shards
- Key shards: `world_state.json`, `player_data.json`, `quest_state.json`, `encounter_state.json`, `fate_state.json`, `game_logs.json`
- Auto-migration for old save formats

### AI Tool Protocol
- Main chat uses `route_main_turn_intent()` to intercept deterministic gameplay actions
- AI tools available for: quests, fate, area reputation, character desires/stories, public scene reading
- Prompts registered in `data/ai-prompts.csv`

## Security Considerations

- `config.json` contains plaintext API keys - **local use only**
- Session cookies are signed with `itsdangerous`
- CORS restricted to local development origins
- Sensitive data (Authorization headers, user privacy) should be redacted in logs
- Auth secret stored in `data/auth/secret.txt` (auto-generated if not provided)

## Requirements Documentation

Key requirements doc: `docs/requirements/pending-2026-03-01.md` captures the fate/quest/encounter implementation scope.

Current feature status as of 2026-03-15:
- ✅ AI configuration with multi-provider support
- ✅ Main narrative chat with SSE streaming
- ✅ World map, regions, sub-zones
- ✅ Fate line generation and progression
- ✅ Quest system (accept/reject/tracking)
- ✅ Encounter system with situation values
- ✅ Character/party management
- ✅ Battle system
- ✅ Debug panel with comprehensive tools
- ✅ Token usage tracking

## Environment Variables

### Backend
- `GRW_AUTH_SECRET` - Session signing secret (optional, auto-generated if not set)

### Frontend (Docker)
- `VITE_BACKEND_URL` - Backend URL for proxy (default: `http://127.0.0.1:8000`)
- `VITE_HOST` - Dev server host (default: `127.0.0.1`)
- `VITE_PORT` - Dev server port (default: `5173`)
- `CHOKIDAR_USEPOLLING` - Enable polling for file watching (Windows Docker)

## Common Issues

1. **Port conflicts**: Change ports in startup commands or Docker compose
2. **Python not found**: Install Python 3.11-3.14 and add to PATH
3. **npm not found**: Install Node.js 20+ and add to PATH
4. **CORS errors**: Ensure backend CORS allows frontend origin
5. **Windows file watching in Docker**: Set `CHOKIDAR_USEPOLLING=true`

## API Base URLs

- Development: `http://127.0.0.1:8000/api/v1`
- Health check: `GET /api/v1/health`
- WebSocket/SSE: Supported for streaming chat

## Contact & References

- Architecture: `docs/technical/mvp-architecture.md`
- Technical index: `docs/technical/technical.md`
- Game design: `docs/design/gamedesign/gamedesign.md`
- Encounter preferences stored in local CSV for global prompt generation
