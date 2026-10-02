# Máquina 1 V5.7 — qualificação e validação

A V5.7 corrige a segunda varredura de instituições sem candidatos: todas as consultas são refeitas. Falhas de conexão continuam retomando a consulta interrompida. A primeira execução reabre uma vez a fila oficial, preservando os leads existentes.

## Critério de aprovação

- Formação em Nutrição e evidência acadêmica datada em 2025 ou 2026.
- Último período, 7º/8º semestre, TCC, estágio final, conclusão e colação de grau são sinais; datas antigas não aprovam.
- Intervalos acadêmicos aceitam semestre (`2021.1–2025.2`) e precisam ter ordem válida.
- Sinais sem data, negações, períodos iniciais, orientadores/docentes e múltiplos cursos exigem revisão. Esses candidatos aparecem no log com motivo, mas não são inseridos como qualificados.
- Ano e período vêm da decisão acadêmica, sem escolher automaticamente qualquer ocorrência de 2026 no perfil.
- A descoberta usa nome e sigla da instituição e consultas para 2025 e 2026.
- O vínculo institucional exige nome completo ou sigla; a correspondência por duas palavras foi removida.

## Testes

`python -m unittest discover -p 'test_*.py' -v`

Há testes de perfis válidos e inválidos, hífens Unicode, intervalos semestrais, empréstimo de evidência de outro perfil, instituições sobrepostas, domínios falsos, indisponibilidade do buscador, segunda varredura, retomada de conexão e inserção apenas de candidato válido. O workflow `Testes de qualificacao de leads` roda sem credenciais e publica o resultado no GitHub Actions.

## Operação

Execute `Automacao Maquina de Leads` em Actions → Run workflow → main. A captura mantém o limite de quatro instituições por execução. Mais consultas aumentam o tempo de execução. Não há agendamento no workflow atual.

Os leads capturados antes da V5.7 não são automaticamente requalificados. Os testes usam exemplos controlados; não medem precisão sobre perfis reais. Uma amostra real deve confirmar instituição, pessoa, curso e data antes de escalar. Candidatos com evidência insuficiente podem exigir consulta à fonte original para aprovação.
