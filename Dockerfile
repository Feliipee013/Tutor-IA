FROM python:3.11-slim

# Evita arquivos .pyc e garante logs em tempo real no console
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# O OCR do Manual (issue #40, ADR-0011) precisa do tesseract com português.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências do projeto
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# Copia código fonte do serviço e o que é versionado do `corpus/`: só o README
# e o `.gitkeep`. O PDF do Manual nunca entra no git nem na imagem — ele chega
# ao container por bind mount (`./corpus:/app/corpus:ro` no `webhook`).
COPY sau/ ./sau/
COPY corpus/README.md corpus/.gitkeep ./corpus/

# 8000 é o serviço do bot (health check); 8080 é o webhook do Telegram, que é
# outro container com outro entrypoint. As duas portas ficam declaradas porque
# `EXPOSE` é documentação da imagem, e o mapeamento quem faz é o compose.
EXPOSE 8000 8080

CMD ["python", "-m", "sau.main"]
