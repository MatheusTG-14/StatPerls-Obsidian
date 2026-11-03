#!/bin/bash
# Double-click to start StatPearls Vault in a Terminal window.
cd "$(dirname "$0")" || exit 1
./statpearls-vault
echo
read -n 1 -s -r -p "Press any key to close this window."
