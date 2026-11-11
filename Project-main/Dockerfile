FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# One class per file: main.py + every manager file + the tests
COPY main.py main_*.py io_manager_*.py ai_manager_*.py logic_manager_*.py data_manager_*.py test_logic.py ./

CMD ["python", "main.py"]
