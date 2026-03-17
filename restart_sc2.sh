#!/bin/bash

# Kill any lingering SC2 processes
echo "Killing StarCraft II processes..."
pkill -9 SC2 2>/dev/null || true
pkill -9 "StarCraft II" 2>/dev/null || true

# Small delay to ensure clean shutdown
sleep 2

# Clear any temporary connections
echo "Clearing temporary files..."
rm -rf /tmp/sc2_* 2>/dev/null || true

echo "StarCraft II cleaned up. You can now start the game again."
