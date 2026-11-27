#!/bin/bash
# Startet Arca-Service und Terminal-Server; endet einer, endet der Container (Docker startet neu).
set -u
arca-service &
node /app/arca/terminal/server.mjs &
wait -n
exit 1
