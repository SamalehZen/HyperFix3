#!/bin/sh
# Swap 4 Go de sécurité (le serveur n'en a pas : sans swap, un pic mémoire
# fait tuer un conteneur au hasard par l'OOM killer, possiblement postgres).
# Idempotent : ne fait rien si le swap est déjà actif.
set -e
if swapon --show=NAME | grep -q .; then
    echo "[swap] déjà actif :"
    swapon --show=NAME,SIZE
    exit 0
fi
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
grep -q "^/swapfile " /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
echo "[swap] OK :"
free -h | head -n 3
