FROM eclipse-temurin:17-jre-jammy

RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv curl \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir playwright pyotp requests

RUN playwright install chromium && playwright install-deps chromium

COPY SureshotSDK/ibkr /opt/ibkr
RUN chmod +x /opt/ibkr/bin/run.sh

COPY live_trading_infrastructure/docker/ib-gateway/start.sh /opt/start.sh
RUN chmod +x /opt/start.sh

ENV PYTHONPATH=/opt/ibkr
WORKDIR /opt/ibkr

CMD ["/opt/start.sh"]
