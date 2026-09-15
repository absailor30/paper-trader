#!/bin/bash
# Autonomous Trading Agent VPS Deployment Script
# Tested on Ubuntu 22.04 / 24.04 LTS (AWS EC2 / Oracle Cloud / DigitalOcean)

set -e

echo "=== 1. System Updates & Docker Setup ==="
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y git curl docker.io docker-compose-v2

sudo systemctl enable --now docker
sudo usermod -aG docker $USER

echo "=== 2. Project Directory Setup ==="
mkdir -p ~/trading-agent
cd ~/trading-agent

echo "=== 3. Ready for Deployment ==="
echo "Clone repo and start container:"
echo "  git clone https://github.com/absailor30/paper-trader.git ."
echo "  cp .env.example .env && nano .env   # Paste API keys"
echo "  docker compose up -d --build"
echo "  docker compose logs -f"
