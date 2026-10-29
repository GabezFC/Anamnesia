"""Build bounded paid-experiment proposal from PUBLIC model tariffs. Does not call a model."""
import json
from decimal import Decimal
from pathlib import Path
R=Path(__file__).resolve().parents[1]
O=R/'data/reports-out/finalizacao-2026-10-28/paid'
d=json.loads((O/'public_pricing.json').read_text())
rows=[]
for m in d['models']:
    p=m['pricing']; n=176; ti=12000; to=512
    unit=Decimal(p['prompt'])*ti+Decimal(p['completion'])*to
    rows.append(dict(model=m['id'],provider='OpenRouter (backend to be pinned before execution)',calls=n,input_tokens=n*ti,output_token_ceiling=n*to,input_usd_per_million=str(Decimal(p['prompt'])*1000000),output_usd_per_million=str(Decimal(p['completion'])*1000000),estimated_usd=str(unit*n),model_cap_usd='1.50' if m['id'].startswith('openai/') else '10.00'))
mini=next(m for m in d['models'] if m['id']=='openai/gpt-4.1-mini')
pilot=16*(Decimal(mini['pricing']['prompt'])*12000+Decimal(mini['pricing']['completion'])*512)
proposal={'status':'NOT AUTHORIZED; NO GENERATION REQUESTS EXECUTED','public_tariff_snapshot':'2026-10-28','tariff_source':d['source'],'provider_balance':'not checked; no credentials read','agent_operations_cost':'not metered; separate from experiment','models':rows,'main_total_calls':sum(r['calls'] for r in rows),'main_estimated_usd':str(sum(Decimal(r['estimated_usd']) for r in rows)),'main_global_cap_usd':'12.00','openrouter_cap_usd':'11.50','typesafe_jev_cap_usd':'0.00','judge_api_calls':0,'pilot':{'model':mini['id'],'calls':16,'estimated_usd':str(pilot),'cap_usd':'0.25','requires_separate_authorization':True}}
(O/'proposal.json').write_text(json.dumps(proposal,indent=2),encoding='utf-8')
lines=['# Proposta de experimentos pagos — NÃO EXECUTADA','','Preços públicos consultados em 28/10/2026; são tarifas, não cobranças nem confirmação de saldo. Endpoint público não autenticado: '+d['source'],
'Consultar preços e endpoint novamente imediatamente antes da execução. Nenhum saldo foi presumido. Não foram lidas credenciais para esta proposta.',
'', '## Etapa piloto opcional (autorização separada)',
f"16 chamadas de openai/gpt-4.1-mini, quatro perguntas sintéticas × quatro braços, uma repetição. Hipótese de 12.000 tokens de entrada por chamada e teto de 512 de saída: US${pilot}. Teto proposto: US$0,25. O objetivo é verificar instrumentação, retenção da resposta factual, budget matching e avaliação determinística; não produzir uma conclusão estatística.",
'', '## Etapa principal proposta (não é continuação automática do piloto)',
'Pergunta A: a redução de contexto continua vantajosa contra OFF-B, com orçamento igual? Pergunta B: Laya usada para selecionar contexto melhora a geração sem custo remoto de reranking? Pergunta C: um agente real retém decisões ao longo de turnos e após reinício, sem informação na conversa nova?',
'Corpus exclusivamente sintético, com fatos/versões e fontes verificáveis. Conjunto de desenvolvimento separado para qualquer calibração; congelar antes dos testes. Laya é seletora local, não um modelo gerador: o gerador mantém-se igual entre braços.',
'Por modelo: 12 perguntas × 4 braços (OFF-A, OFF-B, auto+optimizer, Laya→gerador) × 2 repetições = 96 chamadas. OFF-A: BM25 top-5 notas completas com gate histórico explicitado. OFF-B: BM25 por seções e mesmo orçamento de contexto de auto, contabilizando exatamente o contexto efetivamente entregue. Igualar modelo, prompt, temperatura e limites de saída. Registrar seleção/tokenização e abstenções.',
'Multi-turno/entre sessões: 2 tarefas × 10 turnos × 2 condições COM/SEM × 2 repetições = 80 chamadas por modelo. Usar processos reais de agente, não apenas reconstrução de prompts. Novo processo de sessão B sem histórico de A; COM pode consultar memória salva do corpus sintético, SEM não. Registrar chamadas de ferramentas e impedir vazamento da resposta pelo prompt. Os dez turnos são um piloto de continuidade, não teste de horizonte de dezenas/centenas de turnos.',
'', '| Modelo | Via | Chamadas | Entrada estimada | Saída máxima | US$/M entrada/saída | Estimativa US$ | Teto modelo |',
'|---|---|---:|---:|---:|---|---:|---:|']
for r in rows:
    lines.append(f"| {r['model']} | OpenRouter | {r['calls']} | {r['input_tokens']} | {r['output_token_ceiling']} | {r['input_usd_per_million']}/{r['output_usd_per_million']} | {r['estimated_usd']} | {r['model_cap_usd']} |")
lines += ['', f"Total: {proposal['main_total_calls']} chamadas; estimativa US${proposal['main_estimated_usd']}. É estimativa condicionada a 12k de entrada média, não uma garantia. O crescimento de histórico será contabilizado por chamada e poderá reduzir o número de tarefas executáveis.",
'Teto global proposto US$12,00; subtotal autorizado ao OpenRouter, se aprovado, no máximo US$11,50 (US$1,50 mini + US$10,00 Sonnet). Nenhuma chamada direta a Anthropic/OpenAI e nenhum fallback a outro modelo/provedor. Backend de roteamento deve ser fixado e identificado antes da execução; escolha fora das condições aprovadas exige nova autorização. TypeSafe/JEV: US$0,00 e desabilitado.',
'Juiz pago: nenhuma chamada. Avaliação por fatos sintéticos normalizados, citações e revisão manual auditável; discordâncias ficam explicitamente não decididas. Julgamento com LLM, se depois desejado, exige orçamento próprio.',
'', '## Controles e parada',
'Execução serial. Antes de cada chamada, reservar custo máximo de tokens de entrada contados + saída máxima, sem presumir desconto de cache. Só iniciar se custo acumulado + reserva couber em ambos os tetos (modelo/provedor/global). Saldo, se não verificável sem expor segredo, deve ser confirmado pelo usuário antes do início. Sem retry automático; no máximo uma nova tentativa explicitamente contabilizada dentro do mesmo teto. Parar em erro de preço/usage, vazamento, truncamento do contexto, modelo/backend divergente, indisponibilidade da Laya ou falha do isolamento entre sessões. Não substituir braço ausente por saída simulada.',
'Registrar todos os erros e custos provider-reported, inclusive tentativas repetidas; distinguir tarifas calculadas e fatura. Parar também após duas falhas consecutivas. Sem web search, imagens ou ferramentas remotas cobradas; flags explicitamente desabilitadas.',
'', '## Métricas e limites',
'Acerto factual por pergunta, abstenção apropriada e falsa abstenção, proveniência, tokens de contexto e provider-reported, latência incluindo recuperação, custo da geração, chamadas de ferramenta e resultados por sessão. Comparações pareadas e bootstrap por pergunta/tarefa, sem tratar repetições ou turnos como amostras independentes. Divulgar perdas e pares ausentes. Duas famílias de modelos por um intermediário não equivalem à cobertura de todos os modelos ou de vários provedores diretos.',
'Custo operacional do principal/subagentes: assinatura/uso não medido nesta sessão; não é o orçamento desta tabela. Computação local e eletricidade não estão faturadas aqui.']
(O/'PROPOSTA.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(proposal,indent=2))
