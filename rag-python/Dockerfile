FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app/rag-python

COPY rag-python/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY rag-python/ ./

EXPOSE 18080

CMD ["python", "-m", "app.main"]

