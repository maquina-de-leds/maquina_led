-- Aplicação manual no Supabase: não é executada pela captura ou pelos testes.
-- Preserva todos os registros. A transação aborta se houver duplicados legados.
BEGIN;

CREATE OR REPLACE FUNCTION public.chave_lead_v58(text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE
SET search_path = pg_catalog
AS $$
 SELECT lower(btrim(regexp_replace(
   translate(regexp_replace(normalize(coalesce($1, ''), NFKD), '[̀-ͯ]', '', 'g'),
             '‐‑‒–—−', '------'), '[[:space:]]+', ' ', 'g')))
$$;

ALTER TABLE public.leds ADD COLUMN IF NOT EXISTS duplicado_de bigint;
ALTER TABLE public.leds ADD COLUMN IF NOT EXISTS nao_contatar boolean DEFAULT false;
ALTER TABLE public.leds ADD COLUMN IF NOT EXISTS qualificado boolean DEFAULT false;
ALTER TABLE public.leds ADD COLUMN IF NOT EXISTS proxima_acao text;
LOCK TABLE public.leds IN SHARE ROW EXCLUSIVE MODE;

-- Preserva duplicidades legadas da mesma pessoa/fonte para revisão reversível.
WITH classificados AS (
 SELECT id, first_value(id) OVER (
   PARTITION BY public.chave_lead_v58(nome), fonte_url ORDER BY id
 ) AS principal
 FROM public.leds
 WHERE fonte_url IS NOT NULL AND fonte_url <> ''
   AND origem IS DISTINCT FROM 'teste_automacao' AND duplicado_de IS NULL
)
UPDATE public.leds l SET duplicado_de=c.principal, nao_contatar=true,
 qualificado=false, proxima_acao='revisar_duplicado_legado'
FROM classificados c WHERE l.id=c.id AND c.id<>c.principal;

DO $$ BEGIN
 IF EXISTS (
   SELECT 1 FROM public.leds
   WHERE origem IS DISTINCT FROM 'teste_automacao' AND duplicado_de IS NULL
   GROUP BY public.chave_lead_v58(nome), public.chave_lead_v58(instituicao)
   HAVING count(*) > 1
 ) OR EXISTS (
   SELECT 1 FROM public.leds WHERE fonte_url IS NOT NULL AND fonte_url <> '' AND origem IS DISTINCT FROM 'teste_automacao' AND duplicado_de IS NULL
   GROUP BY public.chave_lead_v58(nome), fonte_url HAVING count(*) > 1
 ) THEN
   RAISE EXCEPTION 'Duplicados legados exigem revisão; nenhum registro foi removido';
 END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS leds_nome_instituicao_v58_unique
 ON public.leds (public.chave_lead_v58(nome), public.chave_lead_v58(instituicao))
 WHERE origem IS DISTINCT FROM 'teste_automacao' AND duplicado_de IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS leds_nome_fonte_v58_unique
 ON public.leds (public.chave_lead_v58(nome), fonte_url)
 WHERE fonte_url IS NOT NULL AND fonte_url <> '' AND origem IS DISTINCT FROM 'teste_automacao' AND duplicado_de IS NULL;

ALTER TABLE public.leds ADD COLUMN IF NOT EXISTS maquina2_verificado_em timestamptz;
ALTER TABLE public.leds ADD COLUMN IF NOT EXISTS maquina2_tentativas integer NOT NULL DEFAULT 0;

COMMIT;

