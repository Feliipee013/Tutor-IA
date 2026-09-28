FROM python:3.11-slim

# Evita arquivos .pyc e garante logs em tempo real no console
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências do projeto
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# Copia código fonte do serviço
COPY sau/ ./sau/

# 8000 é o serviço do bot (health check); 8080 é o webhook do Telegram, que é
# outro container com outro entrypoint. As duas portas ficam declaradas porque
# `EXPOSE` é documentação da imagem, e o mapeamento quem faz é o compose.
EXPOSE 8000 8080

CMD ["python", "-m", "sau.main"]
