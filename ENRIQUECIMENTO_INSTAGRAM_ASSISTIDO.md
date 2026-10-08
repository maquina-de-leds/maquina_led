# Enriquecimento assistido de leads no Instagram

Esta rotina prepara pesquisas para serem abertas e conferidas por uma pessoa no Instagram. Ela não faz login, scraping, nem coleta resultados automaticamente.

## Preparar a fila

Aplicar primeiro `migrations/20261005_instagram_buscas_assistidas.sql` no projeto Supabase. Definir `SUPABASE_URL` e `SUPABASE_KEY` no ambiente. A chave precisa permitir acesso às tabelas com RLS habilitado.

```bash
python instagram_enriquecimento_assistido.py exportar --saida fila_instagram.csv --limite 25
```

O CSV inclui nome, instituição, cidade, estado, consulta `NOME nutrição` e link de pesquisa do próprio Instagram. O script considera apenas leads qualificados sem Instagram e com contato permitido. Não altera a tabela `leds`.

## Pesquisar e importar

Abra cada `instagram_search_url` no Instagram. Copie para o CSV todos os arrobas de perfis que você considerar relacionados à busca. Preencha também, quando disponível, `nome_perfil`, `instagram_url` e `observacao`. Para registrar que não encontrou um perfil para a busca, deixe `instagram` vazio naquela linha.

```bash
python instagram_enriquecimento_assistido.py importar fila_instagram.csv
```

Os perfis entram em `instagram_candidatos` com status `revisar`, vinculados ao lead que originou a pesquisa. Arrobas são normalizados e a unicidade existente no banco impede repetição por maiúsculas/minúsculas. A rotina atualiza o estado da fila em `instagram_buscas`; os dados de `leds` permanecem intactos.

## Testes

```bash
python -m unittest -v test_instagram_enriquecimento_assistido.py
```
