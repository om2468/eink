#!/bin/zsh
# Installs a launchd job that updates the display at the start of every hour.
# To remove it:
#   launchctl bootout gui/$(id -u)/com.eink.dashboard
#   rm ~/Library/LaunchAgents/com.eink.dashboard.plist
set -euo pipefail

LABEL=com.eink.dashboard
REPO=${0:A:h:h}
PLIST=~/Library/LaunchAgents/$LABEL.plist
TARGET=gui/$(id -u)

mkdir -p "$REPO/logs" ~/Library/LaunchAgents

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$REPO/.venv/bin/python</string>
    <string>-m</string>
    <string>dashboard</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartCalendarInterval</key>
  <dict><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$REPO/logs/dashboard.log</string>
  <key>StandardErrorPath</key><string>$REPO/logs/dashboard.log</string>
</dict>
</plist>
EOF

launchctl bootout "$TARGET/$LABEL" 2>/dev/null || true
launchctl bootstrap "$TARGET" "$PLIST"
echo "Installed $LABEL. Logs: $REPO/logs/dashboard.log"
