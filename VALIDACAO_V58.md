# Máquina 1 V5.8 — faculdades, turmas e pessoas

## Fontes e escopo

A lista inicial vem dos microdados oficiais do Censo da Educação Superior 2024 do INEP, publicados em https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-da-educacao-superior . A página consultada em 02/10/2026 lista 2024 como edição mais recente disponível para download. Essa é uma base histórica de oferta; não deve ser apresentada como um catálogo atualizado de todas as instituições existentes em 2026. O cadastro e-MEC é a referência regulatória para complementar e atualizar cursos/instituições: https://www.gov.br/mec/pt-br/politica-regulacao-supervisao-educacao-superior/cadastro-nacional-de-cursos-e-ies .

O cadastro de cursos é cruzado com o de instituições pelo CO_IES. A fila utiliza o município da oferta de Nutrição, não o município da sede ou os estados de outros cursos da instituição. Linhas de turno/curso da mesma faculdade e município são deduplicadas. Os 26 estados e o Distrito Federal precisam estar representados para que a carga nacional seja aceita. O arquivo inteiro é validado antes da gravação.

`python -u scraper.py --preparar-fila` prepara a lista na tabela existente `instituicoes_nutricao`, com estado, cidade, instituição, curso, fonte, data de verificação e status. A primeira publicação executa `Preparar lista de faculdades`. Também pode ser acionado manualmente. O checkpoint da carga impede baixar/processar novamente a cada captura. Se a fonte oficial falhar, a carga fica com erro e a captura não declara cobertura municipal completa. Nenhum lead é apagado. Registros legados da fila que não foram substituídos permanecem, mas são excluídos do processamento pelo filtro de origem da V5.8.

## Captação

Para cada faculdade/município, a Máquina 1 pesquisa nome completo, sigla, Nutrição, 2025/2026 e diferentes sinais: turma, formandos, colação, TCC, concluintes, recém-formados, último período/semestre, estágio final, alunos/conclusão e mostra/autores. Há consultas adicionais com município/UF. LinkedIn é excluído das consultas e seus URLs são bloqueados, inclusive nos redirecionamentos. A Máquina 2 também deixa de pesquisar LinkedIn.

Os nomes são extraídos de páginas e PDFs públicos com vínculo institucional e contexto de Nutrição/ano: listas, tabelas, notícias com relação de formandos, linhas numeradas e metadados de autoria de TCC. Páginas também podem apontar documentos no mesmo domínio, lidos até um nível adicional. Não se usa título de resultado web como nome de pessoa. Professores, orientadores e pessoas de outro curso não são incluídos deliberadamente pelos extratores de listas. Trocas de curso/ano encerram ou atualizam o contexto.

A data da turma prevalece sobre a data da notícia: uma colação publicada em 2026 referente a 2025/2 fica em 2025/2. Quando apenas o ano é comprovado, o semestre fica explicitamente não informado. TCC é registrado como evidência de fase acadêmica; não afirma automaticamente que a pessoa já colou grau.

Quando um Instagram pessoal estiver claramente associado a um único nome da fonte, é salvo junto. O Instagram institucional ou de uma lista coletiva não é distribuído aos alunos. Sem Instagram, o nome é salvo imediatamente e fica com `proxima_acao=buscar_instagram` para a Máquina 2. Nome + instituição continuam sendo a chave de deduplicação utilizada pelo repositório.

## Verificação e operação

### Validação real em 02/10/2026

O ajuste dos extratores passou em 31 testes e em três páginas institucionais reais. A leitura identifica 13 nomes da Unochapecó (2025/2) e um nome da UniAteneu (2026/1). Uma terceira notícia apresenta um nome de Nutrição, mas só fornece ano de publicação: ela não comprova o período acadêmico e não foi usada na gravação. Isso não significa que a pessoa seja inválida; exige confirmação da turma. A ampliação incluiu listas por rótulo de curso e pessoa explicitamente identificada como oradora/formanda de Nutrição, mantendo exclusão de seções docentes e impedindo usar exclusivamente o ano editorial como ano da turma.

Foi feita uma gravação controlada somente dos 14 nomes com semestre explícito. Resultado: 14 candidatos, 14 novos registros, zero duplicados na primeira passagem. Todos ficaram com Instagram pendente. Uma segunda passagem confirmou os 14 no banco e ignorou os 14 como duplicados, sem novas inserções. A validação usou o schema existente do Supabase e não enviou mensagens.

Execução da gravação: https://github.com/maquina-de-leds/maquina_led/actions/runs/37010461518 . Fontes: https://uno.edu.br/noticias/outorga-de-grau-1 e https://uniateneu.edu.br/uniateneu-realizou-colacao-de-grau-para-celebrar-a-formatura-de-alunos-de-diferentes-cursos-de-graduacao/ .

A carga nacional foi corrigida e validada. O arquivo oficial do INEP foi baixado com verificação HTTPS e a intermediária RNP que o servidor omitia, publicada pela Unicamp e conferida pelo SHA-256. As raízes habituais e a verificação de hostname permanecem. Os 139 registros sem município eram linhas de sede EaD: todas essas faculdades já estavam representadas nas ofertas municipais, incluindo os polos. Não foi usada a cidade da sede como cidade da oferta. As 6.461 linhas municipais produziram 6.247 combinações deduplicadas, 620 nomes de faculdades e 1.759 municípios, nos 26 estados e DF.

A lista foi carregada na tabela existente `instituicoes_nutricao`; o total e as 27 contagens por UF foram conferidos contra o arquivo. Execução: https://github.com/maquina-de-leds/maquina_led/actions/runs/37014290195 . O checkpoint concluído evita baixar a base novamente nas próximas capturas. `INEP_CADASTROS_PATH` permite reutilizar os cadastros oficiais já baixados, com as mesmas verificações de ano, vínculo e cobertura nacional. O CSV alternativo do MEC foi testado e retornou HTTP 403; não foi usado como base.

A descoberta web foi testada no próprio runner: cinco resultados para cada uma de duas faculdades. A integração também encontrou a fonte da UniAteneu, leu o nome/período e reconheceu como duplicado o lead anteriormente salvo pela sigla, embora a fila use o nome completo. Execução: https://github.com/maquina-de-leds/maquina_led/actions/runs/37014820171 . Isso comprova esses casos reais, sem garantir rendimento igual para as 620 instituições.

Uma pessoa encontrada em uma fonte da faculdade não recebe automaticamente o município/UF da fila: a cidade precisa aparecer no contexto acadêmico da fonte. Sem essa confirmação, o nome e a instituição podem ser salvos com localização pendente, para não atribuir um aluno de outro campus a um polo EaD arbitrário. Os totais de pendentes por UF usam contagem exata do banco, incluindo estados com mais de mil registros.

`python -m unittest discover -p 'test_*.py'` valida fontes HTML/PDF, cursos e anos distintos, professores, autoria, Instagram associado, filas municipais, repetição de buscas e gravação simulada. Os testes não comprovam desempenho nacional nem substituem validação de uma execução real. O download oficial, schema do Supabase e volume final só são confirmados pelos logs da preparação/captura.

A captura continua em `Automacao Maquina de Leads`, acionada manualmente. Preparação e captura compartilham bloqueio de concorrência. O limite permanece quatro instituições por execução, com checkpoints. Falhas de busca, download ou banco são sinalizadas; uma instituição com fontes inacessíveis fica pendente de revisita. Falha real encerra o job com código diferente de zero.

Limitações: páginas que exigem login/JavaScript, imagens e PDFs digitalizados sem texto não fornecem nomes pelos extratores atuais. Formatos não reconhecidos podem produzir zero nomes. Nesses casos, o log identifica a URL e quantidade extraída para orientar adaptação posterior, sem inventar pessoas ou comprovação. Os leads anteriores não são requalificados em massa.
