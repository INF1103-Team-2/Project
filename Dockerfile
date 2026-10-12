FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py logic_manager.py io_manager.py ai_manager.py data_manager.py test_logic.py ./

CMD ["python", "main.py"]
