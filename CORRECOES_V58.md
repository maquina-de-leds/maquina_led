# Correções da auditoria V5.8 — 04/10/2026

## Comportamento resultante

- Alunos sem fase final comprovada são preservados como candidatos; Instagram não os promove a qualificados.
- A Máquina 2 seleciona novos candidatos e candidatos autorais legados, respeita `nao_contatar` e exige evidência pública compatível de nome, Nutrição, instituição conhecida e fase final antes de qualificar.
- Semestre `2/2025` é registrado como `2025/2`. A fixture do edital real da UNIARP protege os nove nomes, sem copiar títulos ou docentes.
- Consulta parcialmente indisponível mantém pendência. A opção de continuar pesquisas preserva a primeira consulta falhada, mesmo depois de resultados válidos.
- PDF sem texto, PDF acima de 40 páginas e formato não suportado mantêm leitura inconclusiva; alternativa vazia não mascara erro de outra fonte.
- Fontes com falha recebem intervalo crescente e ficam para revisão após cinco tentativas, sem apagar leads ou concluir falsamente a faculdade.
- Deduplicação inclui normalização de acentos, caixa e espaços; retries de banco confirmam se a identidade foi gravada antes de repetir.
- Completar Instagram preserva a validação de candidato. A Máquina 2 falha explicitamente quando não pode verificar o banco e condiciona atualização ao estado atual de qualificação e contato.
- Dependências estão fixadas; CI inclui pdfplumber, fixture documental e PostgreSQL 16 descartável. Alterações em coleções também acionam testes.
- Na auditoria inicial, publicação não disparava gravações. Após ativação autorizada, mudanças na captura disparam um ciclo; captura manual/agendada e Máquina 2 compartilham o bloqueio de concorrência.

## Validação

A suíte contém 202 testes: 196 de extração, qualificação, busca, retomada e banco simulado, mais seis com PostgreSQL descartável (migração idempotente, normalização, preservação de homônimos em instituições distintas, proteção por URL, abortar duplicados legados e inserção simultânea). Localmente, os 196 passaram; os seis SQL são executados no GitHub com serviço de teste. Compilação e `pip check` passaram. As validações de fontes públicas são somente de leitura.

PR e evidências de CI: https://github.com/maquina-de-leds/maquina_led/pull/2

## Ativação no banco e limites

`migrations/001_unicidade_leads.sql` foi preparada e testada em banco descartável. Foi aplicada no Supabase em 04/10/2026 após revisão reversível dos duplicados legados, garantindo unicidade entre processos simultâneos. A migração aborta se encontrar duplicados legados, preservando todos os registros. Consulte `migrations/README.md`.

Não houve gravação de leads, exclusão ou requalificação em massa durante as correções. Registros antigos qualificados exigem uma revisão separada de suas evidências se for desejada atualização retroativa. A fila segue baseada no INEP 2024; não afirma catálogo integral atualizado em 2026. O prazo de execução é cooperativo, e fontes externas podem continuar indisponíveis. Testes verdes não significam varredura nacional completa nem garantia de rendimento.


## Operação nacional e Máquina 2 — atualização de 04/10/2026

- Proteção de unicidade aplicada no Supabase, com 16 duplicidades antigas da mesma pessoa/fonte preservadas e bloqueadas para revisão. Cinco registros de teste foram separados; 17 títulos/perfis institucionais legados foram bloqueados de contato. Nenhuma linha apagada.
- A fila INEP contém 620 instituições distintas, com ofertas nos 26 estados e no Distrito Federal. Isso é a base de pesquisa, não prova de varredura completa.
- Uma vaga por ciclo retoma a faculdade pausada mais antiga; demais vagas avançam a fila. Falha de buscador mantém o checkpoint e não impede as demais faculdades do lote; o ciclo continua sinalizando a falha.
- Captura agendada a cada 30 minutos, com uma execução de ativação ao publicar mudanças na captura. GitHub pode atrasar ou omitir horários; não há garantia de execução contínua.
- Máquina 2 roda após a etapa de captura, mesmo com indisponibilidade de buscador, desde que os testes iniciais tenham passado, no mesmo bloqueio de concorrência. Alterna por última tentativa, tem prazo de cinco minutos por lote e 45 segundos por lead, e exige identidade, curso e vínculo público para associar Instagram. Não envia mensagens.
- O diagnóstico rápido distingue falha de busca de indisponibilidade de página; esta última continua registrada como cobertura incompleta, não é apagada.
- Validação local: 203 testes passaram; oito testes PostgreSQL são executados no serviço descartável do GitHub. Inclui preservação de duplicidades, continuação de lote, retomada e identidade do Instagram.

Validação final no GitHub: 211 testes passaram, incluindo os oito testes PostgreSQL. Evidência: https://github.com/maquina-de-leds/maquina_led/actions/runs/37208369123

## Resultado da execução real de ativação

Execução 37208189934 concluída com sucesso: captura retomou quatro instituições, preservou checkpoints e não gravou novos leads neste lote. Máquina 2 registrou oito tentativas, separou um registro não-pessoa e não confirmou novos Instagrams; seis tentativas atingiram o prazo e seguem pendentes. Base após o lote: 474 registros brutos, cinco testes e 344 marcados como qualificados sem bloqueio de contato. Uma nova execução (37208727026) iniciou a captura; o agendamento continua a cada 30 minutos, sujeito ao serviço do GitHub. Não há garantia de volume, de todos os contatos estarem disponíveis ou de revisão individual dos 344 registros.

## Escopo atual confirmado pelo usuário — somente Máquina 1

Em 04/10/2026, a chamada automática da Máquina 2 foi removida de automacao.yml. A execução anterior 37208727026 foi cancelada durante a captura e sua etapa da Máquina 2 foi ignorada. A execução 37209070737 iniciou apenas testes e captura da Máquina 1, retomando os checkpoints. O agendamento permanece a cada 30 minutos. Publicações de alterações interrompem o ciclo antigo para adotar o novo código; os disparos agendados não cancelam o ciclo ativo. Máquina 2 fica para configuração posterior de busca de Instagram dos leads sem contato. As notas de ativação da Máquina 2 acima descrevem o histórico, não o escopo atual. Foram agendadas três verificações somente de leitura do rendimento às 12h30, 13h30 e 14h30 (Brasília), sem acionar a Máquina 2.
