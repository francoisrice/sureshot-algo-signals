FROM python:3.8-slim
# FROM sureshotcapital/incredibleleverage:latest
WORKDIR /app
COPY /IncredibleLeverageSPXL/main.py /app/main.py
COPY /SureshotSDK /app/SureshotSDK
COPY /IncredibleLeverageSPXL/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt
# CMD ["python", "/app/main.py"]
CMD ["/bin/bash"]
