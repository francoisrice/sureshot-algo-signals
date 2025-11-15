FROM python:3.8-slim
WORKDIR /app
COPY SureshotSDK /app/SureshotSDK
COPY portfolio_IL_efficientfrontier/IncredibleLeverageSPXL/main.py /app/main.py
COPY portfolio_IL_efficientfrontier/IncredibleLeverageSPXL/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
CMD ["python", "/app/main.py"]
