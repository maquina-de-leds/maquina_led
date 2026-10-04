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

LOCK TABLE public.leds IN SHARE ROW EXCLUSIVE MODE;

DO $$ BEGIN
 IF EXISTS (
   SELECT 1 FROM public.leds
   GROUP BY public.chave_lead_v58(nome), public.chave_lead_v58(instituicao)
   HAVING count(*) > 1
 ) OR EXISTS (
   SELECT 1 FROM public.leds WHERE fonte_url IS NOT NULL AND fonte_url <> ''
   GROUP BY public.chave_lead_v58(nome), fonte_url HAVING count(*) > 1
 ) THEN
   RAISE EXCEPTION 'Duplicados legados exigem revisão; nenhum registro foi removido';
 END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS leds_nome_instituicao_v58_unique
 ON public.leds (public.chave_lead_v58(nome), public.chave_lead_v58(instituicao));
CREATE UNIQUE INDEX IF NOT EXISTS leds_nome_fonte_v58_unique
 ON public.leds (public.chave_lead_v58(nome), fonte_url)
 WHERE fonte_url IS NOT NULL AND fonte_url <> '';

COMMIT;
