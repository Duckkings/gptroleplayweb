# OpenHands Local Startup Notes

## Final Working Approach

Use `start-openhands-stable (1).bat` from the repository root.

The working configuration is:

- Use Docker directly on Windows, not `wsl docker`
- Use OpenHands image version `1.4.0`
- Mount the repo root to `/workspace/project`, not `/workspace`

## Why This Works

### 1. `project` folder problem

OpenHands 1.4.0 uses `/workspace/project` as the default working directory.

Relevant behavior:

- OpenHands creates or expects the conversation workspace at `/workspace/project`
- If the host directory is mounted only to `/workspace`, OpenHands may create a `project` subfolder inside the mounted directory

Fix:

- Mount the host repo directly to `/workspace/project`

That keeps the actual OpenHands working directory aligned with the repo root.

### 2. Windows `--mount-cwd` problem

`openhands serve --mount-cwd` on this machine passed a Windows path like:

`C:\Project\gptroleplayweb:/workspace:rw`

But OpenHands inside the container expects Linux-style mount paths for `SANDBOX_VOLUMES`.

Fix:

- Do not use `openhands serve --mount-cwd` here
- Manually pass a Docker Desktop Linux-style host path:
  `/run/desktop/mnt/host/c/...`

### 3. WSL startup problem

The original batch file used `wsl docker run ...`, but the local environment had WSL access issues.

Fix:

- Call `docker.exe` directly from Windows

## Current Batch File Behavior

The current `start-openhands-stable (1).bat` does this:

- Resolves the batch file directory as the repo root
- Converts `C:\...` to `/run/desktop/mnt/host/c/...`
- Starts OpenHands with:
  `SANDBOX_VOLUMES=<repo>:/workspace/project:rw`

## Current Known-Good Settings

- App image:
  `docker.openhands.dev/openhands/openhands:1.4.0`
- Runtime image:
  `docker.openhands.dev/openhands/runtime:1.4.0-nikolaik`
- OpenHands home:
  `%USERPROFILE%\.openhands`
- Web UI:
  `http://localhost:3000`

## If It Breaks Again

Check these first:

1. Docker Desktop is running
2. Port `3000` is free
3. The batch file is still mounting to `/workspace/project`
4. The image version is still `1.4.0`
