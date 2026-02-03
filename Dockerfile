FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# إعداد متغيرات البيئة لرؤية السجلات فوراً
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "src.main"]