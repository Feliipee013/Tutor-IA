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

EXPOSE 8000

CMD ["python", "-m", "sau.main"]
