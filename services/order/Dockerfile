# Build from the repository root:  docker build -f services/order/Dockerfile -t campuseats/order-service .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=5003
WORKDIR /app
COPY services/order/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common/ ./common/
COPY services/order/app.py .
RUN useradd --system --uid 10001 appuser
USER appuser
EXPOSE 5003
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5003/health', timeout=2)"
# One worker + threads keeps start-up (table creation / seeding) race-free; scale with replicas instead.
CMD ["gunicorn", "--bind", "0.0.0.0:5003", "--workers", "1", "--threads", "4", "--timeout", "30", "app:create_app()"]
