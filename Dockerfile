FROM python:3.10-slim

WORKDIR /app

# constraints.txt is the full pip freeze of the deployed container, so
# rebuilds reproduce it exactly (transitive deps included).
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]