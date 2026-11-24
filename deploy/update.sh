#!/usr/bin/env bash
# Put a new version of Clip Studio on the server: pack and upload the new project files the same way as the first install
# (see the top of deploy/setup_vps.sh), unpack them into a fresh folder and run inside it:
#       bash deploy/update.sh                   or, if you gave the studio its own name:     APP_NAME=studio2 bash deploy/update.sh
# It copies the program, installs any new Python packages and restarts only this studio. Your videos, settings and keys are not touched,
# and nothing that belongs to your other apps is changed.
set -euo pipefail
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/setup_vps.sh" --update
