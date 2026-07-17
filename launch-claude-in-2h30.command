#!/bin/zsh

set -euo pipefail

# Le projet correspond automatiquement au dossier contenant ce script
PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PROMPT_FILE="$PROJECT_DIR/prompt.txt"

DELAY_SECONDS=8400          # 2 h 30
AWAKE_SECONDS=8600          # Un peu plus de 2 h 30

if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "Erreur : fichier introuvable :"
    echo "$PROMPT_FILE"
    exit 1
fi

# Script qui sera réellement lancé dans 2 h 30
RUNNER_TEMP="$(mktemp /tmp/claude-fable-runner.XXXXXX)"
RUNNER_FILE="${RUNNER_TEMP}.command"
mv "$RUNNER_TEMP" "$RUNNER_FILE"

{
    echo '#!/bin/zsh'
    echo 'set -e'
    printf 'cd %q\n' "$PROJECT_DIR"
    printf 'PROMPT_FILE=%q\n' "$PROMPT_FILE"
    echo 'claude --model fable --effort ultracode "$(cat "$PROMPT_FILE")"'
} > "$RUNNER_FILE"

chmod +x "$RUNNER_FILE"

# Programme l’ouverture du Terminal dans 2 h 30
nohup zsh -c 'sleep "$1"; open -a Terminal "$2"' \
    _ "$DELAY_SECONDS" "$RUNNER_FILE" \
    > /tmp/claude-delayed-launch.log 2>&1 &

LAUNCH_PID=$!

# Empêche le Mac de dormir pendant l’attente
caffeinate -t "$AWAKE_SECONDS" \
    > /tmp/claude-caffeinate.log 2>&1 &

echo
echo "Claude est programmé dans 2 h 20."
echo "Projet : $PROJECT_DIR"
echo "Prompt : $PROMPT_FILE"
echo "PID du lancement différé : $LAUNCH_PID"
echo
echo "Pour annuler : kill $LAUNCH_PID"