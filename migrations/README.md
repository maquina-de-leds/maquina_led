# Proteção de duplicados no Supabase

`001_unicidade_leads.sql` acrescenta unicidade canônica de nome/instituição e nome/URL, inclusive sob inserções simultâneas. Não apaga, funde ou requalifica leads. Precisa ser aplicada por quem tem acesso ao SQL do Supabase; publicar código não ativa o índice.

Execute primeiro em uma cópia de teste. Em produção, o script bloqueia brevemente a tabela durante a verificação/criação; use uma janela sem captura. Se já houver duplicados, a transação aborta e preserva a base. Revise os duplicados antes de tentar novamente. Não remova as verificações para forçar a execução.

Até aplicar a migração, a deduplicação do aplicativo e o bloqueio dos workflows reduzem duplicados, mas não garantem exclusão de corridas entre processos externos. Os retries confirmam se a identidade já existe antes de tentar gravar novamente.

As normalizações cobrem caixa, espaços, acentos decompostos e variantes de hífen. Não confundem instituições diferentes apenas por nome parecido ou sigla; os aliases continuam sendo resolvidos pela evidência.

Registros antigos não são requalificados automaticamente. Candidatos legados com `fonte_validacao=candidato_autoral_curso_a_validar` já entram na validação da Máquina 2; os novos usam `proxima_acao=validar_fase_academica`.


Aplicada em 04/10/2026: índices de identidade/fonte ativos; duplicidades de fonte preservadas em `duplicado_de`, testes excluídos da unicidade. Campos de rotação da Máquina 2 adicionados. RLS continua habilitada e acesso público fechado.
