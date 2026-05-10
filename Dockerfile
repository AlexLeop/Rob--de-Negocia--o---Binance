FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Transforma o script em executável
RUN chmod +x start.sh

# Libera a porta 8501 do Streamlit
EXPOSE 8501

CMD ["./start.sh"]