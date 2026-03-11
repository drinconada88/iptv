FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Directorio para datos persistentes (M3U, config)
RUN mkdir -p /data

EXPOSE 5000

ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]
