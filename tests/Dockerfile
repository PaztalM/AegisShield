FROM python:3.14.10-slim

WORKDIR /app

COPY tests/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/rules.py ./worker/rules.py
COPY tests/ ./tests/

ENV PYTHONPATH=/app

CMD ["python", "-m", "pytest", "tests", "-v"]
