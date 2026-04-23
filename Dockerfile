FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir asyncssh requests python-dotenv

COPY honeypot/ ./honeypot/

CMD ["python", "-m", "honeypot.ssh_handler"]
