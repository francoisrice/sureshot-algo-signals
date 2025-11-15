FROM python:3.8-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY EfficientFrontier/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY EfficientFrontier /app/EfficientFrontier

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "EfficientFrontier.main:app", "--host", "0.0.0.0", "--port", "8000"]
