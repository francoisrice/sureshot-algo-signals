#!/bin/bash
set -euo pipefail

echo "[ibkr-gateway] Starting Client Portal Gateway..."
./bin/run.sh root/conf.yaml &
GATEWAY_PID=$!

echo "[ibkr-gateway] Waiting for gateway on port 5000..."
for i in $(seq 1 30); do
    if curl -sk https://localhost:5000/v1/api/one/user > /dev/null 2>&1; then
        echo "[ibkr-gateway] Gateway ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[ibkr-gateway] Timeout: gateway did not start within 60s."
        exit 1
    fi
    sleep 2
done

echo "[ibkr-gateway] Running initial authentication..."
python3 -c "
from automation.headless_auth import sync_login
result = sync_login()
if result != 'Login Successful':
    raise SystemExit('Authentication failed: ' + str(result))
print('[ibkr-gateway] ' + result)
"

echo "[ibkr-gateway] Watching gateway process (PID $GATEWAY_PID)..."
wait $GATEWAY_PID
echo "[ibkr-gateway] Gateway process exited."
