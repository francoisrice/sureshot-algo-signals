#!/bin/bash

# cd automation/

# Load DockerHub Credentials from Vault
export DOCKER_USERNAME=$(vault kv get -field=username secret/dockerhub)
export DOCKER_PASSWORD=$(vault kv get -field=password secret/dockerhub)
docker login -u "$DOCKER_USERNAME" -p "$DOCKER_PASSWORD"

# Build Trading Strategy Containers
docker build -t incredibleleverage:spxl IncredibleLeverageSPXL/ && \
docker build -t incredibleleverage:ptir IncredibleLeveragePTIR/ && \
docker build -t incredibleleverage:nvdl IncredibleLeverageNVDL/ && \
docker build -t incredibleleverage:hood IncredibleLeverageHOOD/ && \
docker build -t incredibleleverage:avl IncredibleLeverageAVL/

kubectl apply -f EfficientFrontier.yaml