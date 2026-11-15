FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# One class per file: main.py + every manager file + the tests
COPY main.py main_*.py ai_manager_*.py data_manager_*.py ./
COPY io_manager ./io_manager 
COPY logic_manager ./logic_manager
COPY test_logic.py ./

CMD ["python", "main.py"]