FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y git unzip patch && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app /app/app
COPY config /app/config
RUN mkdir -p /app/data /app/uploads
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
