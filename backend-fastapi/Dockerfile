FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y git unzip patch && rm -rf /var/lib/apt/lists/*
COPY backend-fastapi/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY backend-fastapi/app /app/app
RUN mkdir -p /app/data /app/uploads
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
