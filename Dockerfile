FROM python:3.10-slim

WORKDIR /app

# constraints.txt is the full pip freeze of the deployed container, so
# rebuilds reproduce it exactly (transitive deps included).
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# Only the submitted Python child switches to this uid. The server retains its
# existing identity/network and can still translate using its own credentials.
RUN groupadd --gid 20001 code-exec \
    && useradd --uid 20001 --gid code-exec --no-create-home \
       --home-dir /nonexistent --shell /usr/sbin/nologin code-exec

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
