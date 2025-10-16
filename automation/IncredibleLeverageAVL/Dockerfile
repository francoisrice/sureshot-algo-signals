FROM python:3.8-slim
WORKDIR /app
COPY /IncredibleLeverageAVL/main.py /app/main.py
COPY /SureshotSDK /app/SureshotSDK
COPY /IncredibleLeverageAVL/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt
CMD ["python", "/app/main.py"]
