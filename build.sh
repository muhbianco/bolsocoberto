#!/bin/sh
# Build LOCAL. Produção: push no main (Woodpecker). `prod` só como break-glass.
set -e
cd "$(dirname "$0")"

IMAGE_LOCAL="bolsocoberto:latest"
IMAGE_REMOTE="muhrilobianco/bolsocoberto:latest"

docker builder prune -f
docker build -t "$IMAGE_LOCAL" .
docker tag "$IMAGE_LOCAL" "$IMAGE_REMOTE"

if [ "$1" = "prod" ]; then
  docker login
  docker push "$IMAGE_REMOTE"
  echo "Imagem publicada: $IMAGE_REMOTE"
else
  echo "Build local ok: $IMAGE_LOCAL"
  echo "Tag pronta: $IMAGE_REMOTE"
  echo "Para publicar: ./build.sh prod  |  no Windows: .\\build.ps1 prod"
fi
