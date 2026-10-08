# Installing Podman on Windows

The project database runs in a container. On Linux and Mac you can install Podman directly. On Windows, Podman runs a small Linux system in the background using WSL2, so it needs a few extra steps.

Requires Windows 10 (build 19043 or newer) or Windows 11.

## Steps

```powershell
# 1. Turn on WSL2 (open PowerShell as Administrator)
wsl --install --no-distribution
# Restart your computer when it asks you to

# 2. Install Podman
winget install RedHat.Podman
# or download the installer from https://github.com/containers/podman/releases

# 3. Start Podman's background Linux system
podman machine init
podman machine start

# 4. Check that it worked
podman machine list
podman info
```

After this, `podman` commands work the same on Windows as on Linux or Mac. Run them from PowerShell or a WSL2 terminal.

## Starting the database

Follow the setup section in the main [README](../../README.md). It uses the project's docker compose setup, which Podman can usually run through `podman compose`. Use the exact command from the README.

## If something fails

- `podman machine start` fails: WSL2 is usually not fully enabled, or virtualization is turned off in the BIOS. Check both first.
- Port 3306 already in use: another MariaDB or MySQL is running on your computer. Stop it, or change the port mapping in the compose file.
