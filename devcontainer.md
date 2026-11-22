# Dev Container

This repository includes a [Dev Container](https://containers.dev/) setup in [.devcontainer/](.devcontainer/). It provides a ready-to-use development environment with a local MQTT broker.

## Overview

| File | Purpose |
|------|---------|
| [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json) | Dev container definition: features, VS Code extensions, setup commands |
| [.devcontainer/docker-compose.yaml](.devcontainer/docker-compose.yaml) | Services `dev` (workspace) and `mosquitto` (MQTT broker) |
| [.devcontainer/config.yaml](.devcontainer/config.yaml) | Resampler configuration for development (points to the `mosquitto` service) |
| [.devcontainer/devcontainer-lock.json](.devcontainer/devcontainer-lock.json) | Pinned versions of the dev container features |

### Services

- **dev**: `mcr.microsoft.com/devcontainers/python:3-3.13`. The repository is mounted at `/workspaces/mqtt-resampler`.
- **mosquitto**: `eclipse-mosquitto:2` without authentication. Inside the container network it is reachable as `mosquitto:1883`, and on the host as `localhost:1883`.

### Features and tools

- Node.js (devcontainer feature)
- Claude Code (devcontainer feature and VS Code extension). Its configuration is kept in the named volume `claude-config` so it survives container rebuilds.
- Python extension for VS Code
- `mosquitto-clients` (`mosquitto_pub`, `mosquitto_sub`) for manual testing

### Setup on creation (`postCreateCommand`)

1. Copies the deploy key to `~/.ssh/deploy_key` with mode `600` (see below)
2. Fixes ownership of `~/.claude`
3. Runs `pip install -r requirements.txt`
4. Installs `mosquitto-clients`

## Usage

1. Open the repository in VS Code and choose **Dev Containers: Reopen in Container**.
2. Start the resampler:
   ```bash
   python main.py
   ```
   The environment variable `CONFIG_FILE` points to `.devcontainer/config.yaml`, so the development configuration is used automatically. Without `CONFIG_FILE`, `main.py` falls back to `config.yaml`.
3. Send test messages and watch the output:
   ```bash
   mosquitto_sub -h mosquitto -t 'gridmeter/#' -v
   mosquitto_pub -h mosquitto -t gridmeter/sensor/powerconsumecurrent/state -m 42
   ```

## Git access via deploy key

Inside the container, Git authenticates against GitHub with a **dedicated deploy key** that is configured for this repository only. Your personal SSH keys and the host's SSH agent are deliberately **not** passed into the container.

### How it works

- **On the host:** the private key is at `~/.ssh/tgruenert-github-private-repos`.
- **Mount:** `docker-compose.yaml` mounts it read-only at `/run/deploy_key`.
- **Copy:** `postCreateCommand` copies it to `/home/vscode/.ssh/deploy_key` with owner `vscode` and mode `600`. SSH refuses keys with looser permissions.
- **Git:** `GIT_SSH_COMMAND` makes Git use only this key:
  ```
  ssh -i /home/vscode/.ssh/deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new
  ```
  `StrictHostKeyChecking=accept-new` accepts GitHub's host key on first connect and stores it in `~/.ssh/known_hosts`.
- **No agent forwarding:** `remoteEnv.SSH_AUTH_SOCK` is set to empty. This stops VS Code from forwarding the host's SSH agent, so no other keys are available in the container.
- **Remote:** `origin` uses SSH: `git@github.com:tgruenert/mqtt-resampler.git`

Push and pull work with this setup. A push from the container has been tested successfully.

### Setting up the deploy key (one-time, on the host)

1. Generate the key pair:
   ```bash
   ssh-keygen -t ed25519 -C "deploy-key mqtt-resampler" -f ~/.ssh/tgruenert-github-private-repos -N ""
   ```
2. Add the public key (`~/.ssh/tgruenert-github-private-repos.pub`) on GitHub under **Settings → Deploy keys → Add deploy key**. Enable **Allow write access** so you can push.
3. Rebuild the container: **Dev Containers: Rebuild Container**.

### Checking and troubleshooting

```bash
ssh -i ~/.ssh/deploy_key -o IdentitiesOnly=yes -T git@github.com   # expected: "Hi tgruenert/mqtt-resampler! ..."
ls -l ~/.ssh/deploy_key                                             # expected: -rw------- vscode vscode
```

- **`Permission denied (publickey)`:** check that the public key is registered as a deploy key on the repository and that the file exists on the host.
- **Push rejected:** the deploy key has no write access.
- **Mount error on container start:** the key file is missing on the host. `${HOME}/.ssh/tgruenert-github-private-repos` must exist.

### Security notes

- The private key is never stored in the repository. It is only mounted from the host.
- A deploy key only grants access to this one repository. If it leaks, delete it on GitHub and generate a new one.
