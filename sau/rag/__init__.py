"""Recuperação do S.A.U.: embeddings locais e índice em memória do Corpus.

O Corpus (`corpus/`) é o material sobre o processo de Estágio que o S.A.U.
responde, e este pacote é o caminho entre ele e o prompt: `embed` transforma
texto em vetor pelo Ollama do host, e `retrieve` monta o índice em memória a
partir das seções do Corpus. O índice nunca é persistido em disco — um índice
em disco é um segundo artefato que precisa ser sincronizado com o Corpus, e um
índice desatualizado mede em silêncio.
"""
