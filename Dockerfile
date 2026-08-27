FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# SQLite cache lives here, backed by the named volume text_data
RUN mkdir -p /app/data
ENV TEXT_DB=/app/data/text.db

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
