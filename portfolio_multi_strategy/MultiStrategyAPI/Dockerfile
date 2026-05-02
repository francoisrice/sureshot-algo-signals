FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install SDK deps first — layer cache is reused unless requirements.txt changes
COPY SureshotSDK/requirements.txt ./sdk-requirements.txt
RUN pip install --no-cache-dir -r sdk-requirements.txt
RUN playwright install chromium && playwright install-deps chromium

# Install API-specific deps
COPY portfolio_multi_strategy/MultiStrategyAPI/requirements.txt ./api-requirements.txt
RUN pip install --no-cache-dir -r api-requirements.txt

# Install SureshotSDK as a package
COPY SureshotSDK/ ./SureshotSDK/
RUN pip install --no-cache-dir -e ./SureshotSDK/

# Copy MultiStrategyAPI source
COPY portfolio_multi_strategy/MultiStrategyAPI/ ./MultiStrategyAPI/

ENV PYTHONPATH=/app

CMD ["uvicorn", "MultiStrategyAPI.main:app", "--host", "0.0.0.0", "--port", "8000"]
