FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libopus0 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home bot
COPY main.py .
USER bot
CMD ["python", "-u", "main.py"]
