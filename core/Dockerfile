FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

# Prevent Python buffering issues in logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Copy dependency list first (better build caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ensure chromium is present in this image environment
RUN playwright install chromium

# Copy project
COPY . .

# Streamlit config
EXPOSE 8501

# Render provides $PORT. Streamlit must bind to it.
CMD streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true