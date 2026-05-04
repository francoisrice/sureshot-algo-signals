FROM python:3.12-slim

WORKDIR /app

# Install SDK deps (includes playwright Python package but not the browser binary —
# this container never calls headless_auth directly)
COPY SureshotSDK/requirements.txt ./sdk-requirements.txt
RUN pip install --no-cache-dir -r sdk-requirements.txt

# Install SureshotSDK as a package
COPY SureshotSDK/ ./SureshotSDK/
RUN pip install --no-cache-dir -e ./SureshotSDK/

# Copy strategy source
COPY portfolio_multi_strategy/ORB_Aziz_TQQQ/ ./strategy/

ENV PYTHONPATH=/app

CMD ["python3", "strategy/main.py"]
