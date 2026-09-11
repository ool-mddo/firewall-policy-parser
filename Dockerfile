FROM python:3.12-slim

WORKDIR /app

COPY requirements_prod.txt .
RUN pip install --no-cache-dir -r requirements_prod.txt

COPY src/ src/

EXPOSE 5000

ENV MDDO_FIREWALL_POLICY_PARSER_DIR=/app

CMD ["python3", "src/app.py"]
