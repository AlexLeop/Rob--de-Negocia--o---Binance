# Plano de Implementação: Correções HFT e Upgrades Rust (Revisado)

Após um questionamento profundo sobre as implicações de cada upgrade no ecossistema atual, identifiquei **4 falhas lógicas graves** que ocorreriam se aplicássemos as sugestões diretamente sem adaptação. 

## 🧠 Insights Críticos (Por que o plano original falharia)

1. **Posições Órfãs no Auto-Scanner (Perigo de Liquidação)**:
   Se o `auto_scan_pairs` rodar a cada 6h e simplesmente substituir as moedas no banco de dados, o `main.py` detectará a mudança e cancelará as threads antigas (`tarefas.cancel()`). Se um dos pares antigos estivesse com uma **posição aberta**, a thread morre, o bot "esquece" do par, mas a posição continua aberta na Binance!
   *Correção:* O Auto-Scanner fará um pre-flight check. Se houver **qualquer posição aberta** na conta, ele adiará a rotação de pares para evitar o abandono de posições ativas.

2. **O Health Checker Travando Saídas (Armadilha)**:
   Se a API ficar instável e o `ApiHealthTracker` forçar um `await asyncio.sleep(60)`, isso ocorrerá no topo do loop. Se já houver uma posição aberta querendo atingir o Stop Loss ou Take Profit, o bot ficará cego e inativo por 60 segundos! 
   *Correção:* O bloqueio do Health Checker só deve impedir a **entrada em novas posições**. Se o par já estiver aberto (`is_open = True`), o bot deve ignorar a instabilidade e lutar agressivamente para fechar a operação.

3. **Falso Supervisor (Exceções Silenciadas)**:
   O código atual de `monitorar_par` possui um `while True:` com um `except Exception:` genérico que nunca dá `raise`. Se implementarmos o `supervisor_par` por cima dele, o supervisor **nunca será acionado**, pois as falhas nunca sobem.
   *Correção:* Limpar a estrutura do `monitorar_par` para que ele levante (bubble up) as exceções, permitindo que o `supervisor_par` faça seu trabalho de contagem de falhas e circuit breaker isolado.

4. **Aviso de Depreciação no Pandas (Vectorized Beta)**:
   O método `.fillna(method='ffill')` do Pandas está obsoleto nas versões recentes (>= 2.1.0).
   *Correção:* Usaremos a sintaxe moderna `.ffill().fillna(1.0)` para garantir compatibilidade futura.

---

## User Review Required
> [!IMPORTANT]
> - O `TRADE_AMOUNT_USD` será ajustado para 30.00, `TARGET_PNL` para 1.50 e `STOP_LOSS` para 1.00.
> - O `TESTNET` será gerenciado via `.env` ou configurações de ambiente.
> - Por favor, revise os insights e **aprove este plano final** para que eu inicie a reescrita do código imediatamente.

## Proposed Changes

---

### Configurações Globais & Variáveis de Ambiente
#### [MODIFY] [config.py](file:///c:/Users/lxleo/Documents/Meus%20Rob%C3%B4s/Rob%C3%B4%20de%20Paris%20Trade%20-%20Binance%20Python/config.py)
- Adicionar leitura de `TESTNET = os.getenv("TESTNET", "true").lower() == "true"`.
- Modificar default: `TRADE_AMOUNT_USD = 30.0`.
- Modificar default: `TARGET_PNL = 1.50`.
- Modificar default: `STOP_LOSS = 1.00`.

#### [MODIFY] [database.py](file:///c:/Users/lxleo/Documents/Meus%20Rob%C3%B4s/Rob%C3%B4%20de%20Paris%20Trade%20-%20Binance%20Python/database.py)
- Atualizar o dicionário `default_configs` para os novos valores de trade, target e stop (R:R 1.5:1).

---

### Execução e Saúde da API (Integração Rust)
#### [NEW] [api_health.py](file:///c:/Users/lxleo/Documents/Meus%20Rob%C3%B4s/Rob%C3%B4%20de%20Paris%20Trade%20-%20Binance%20Python/api_health.py)
- Criar a classe `ApiHealthTracker` (window=20, threshold=0.40) para monitorar uptime de RPC.

#### [MODIFY] [exchange.py](file:///c:/Users/lxleo/Documents/Meus%20Rob%C3%B4s/Rob%C3%B4%20de%20Paris%20Trade%20-%20Binance%20Python/exchange.py)
- `AsyncClient.create(..., testnet=Config.TESTNET)`.
- Instanciar `self.health = ApiHealthTracker()`.
- Envolver as chamadas `execute_market_order` e `get_klines` em `try/except` para gravar `.record(True)` ou `.record(False)`.

---

### Otimização Matemática
#### [MODIFY] [strategy.py](file:///c:/Users/lxleo/Documents/Meus%20Rob%C3%B4s/Rob%C3%B4%20de%20Paris%20Trade%20-%20Binance%20Python/strategy.py)
- Implementar o `@staticmethod rolling_beta_vectorized(log_a, log_b, window)` sem os comandos obsoletos do Pandas.
- Substituir o loop lento (O(n²)) dentro do `calculate_indicators` por esta chamada vetorizada.

---

### Arquitetura Principal
#### [MODIFY] [main.py](file:///c:/Users/lxleo/Documents/Meus%20Rob%C3%B4s/Rob%C3%B4%20de%20Paris%20Trade%20-%20Binance%20Python/main.py)
- **Saúde da API (Smart Block)**: `if not executor.health.is_healthy() and not is_open:` no topo do ciclo.
- **Supervisor Adaptado**: Adicionar `supervisor_par`, removendo a captura genérica do `monitorar_par` e permitindo que as exceções borbulhem.
- **Scanner Inteligente**: `auto_scan_pairs` usará `futures_position_information()` para abortar o scan se detectar qualquer posição aberta, evitando orfanar o ativo.

## Verification Plan
1. Iniciar o bot e validar se o Risco:Retorno foi aplicado ($30 / $1.50 / $1.00).
2. Simular um erro de rede para confirmar que o `api_health.py` bloqueia apenas entradas, e não saídas.
3. Forçar um exception no `monitorar_par` e checar o log para ver o `supervisor_par` interceptando o erro, contando a falha e reiniciando a task sem derrubar as demais.
