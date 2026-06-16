# Auditoria Cirúrgica: Paris Trade HFT (Binance Python)

Realizei uma análise profunda no código fonte do seu bot (arquitetura, concorrência, interação com API, lógica estatística e UI). Abaixo estão documentados todos os bugs críticos (alguns perigosos para a operação real), bugs lógicos e propostas avançadas de upgrade institucional.

---

## 🚨 Bugs Críticos e Erros de Lógica

### 1. Colisão de Dados de Múltiplos Pares no Dashboard (Race Condition)
- **Local:** `main.py` (linhas 56-59) e `dashboard.py` (linhas 190-192)
- **Problema:** As chaves de status no banco de dados (`LIVE_ZSCORE`, `LIVE_ADX`, `LIVE_STATUS`) são globais e hardcoded. Se você roda mais de um par simultaneamente (ex: ADA/XRP e OP/ARB), todas as threads assíncronas do bot tentam reescrever os mesmos campos ao mesmo tempo.
- **Consequência:** O Dashboard (Streamlit) apresentará uma "salada de dados", piscando entre os Z-Scores de diferentes ativos de forma caótica. Apenas o dado do último par a atualizar sobreviverá.
- **Solução:** Dinamizar as chaves no banco de dados (ex: `LIVE_ZSCORE_ADAUSDT_XRPUSDT`) e renderizar um grid de "cards" no Streamlit para cada par em operação.

### 2. Zombie Tasks e Risco no Encerramento de Posições (Asyncio)
- **Local:** `main.py` (linhas 141-147)
- **Problema:** No bloco `except asyncio.CancelledError:`, se a thread estiver em zona crítica, o código faz um `continue` para tentar "salvar" a execução.
- **Consequência:** Ao suprimir um `CancelledError` sem fazer o re-raise (`raise`), o asyncio falha em finalizar a task corretamente. A rotina vira uma "Zombie Task", mantendo loops ativos em background invisíveis, travando o sistema e podendo duplicar ordens caso o bot seja reiniciado.
- **Solução:** Utilizar um bloco `finally` para o cleanup (fechar posições de forma atômica se necessário) e garantir que a exceção flua (remover o `continue` ou dar um `raise` no final).

### 3. Falha Silenciosa de Reindexação Temporal (Pandas)
- **Local:** `strategy.py` (linhas 37-40)
- **Problema:** O método `pd.infer_freq` pode falhar (retornar `None`) ou conflitar. Se o timeframe configurado for `1h`, o `except` atual chuta `'5min'` de fallback arbitrário para o indexador.
- **Consequência:** Se o bot falhar na inferência operando no gráfico de 1h ou 15m, ele interpolará o DataFrame para intervalos de 5 minutos, duplicando velas e distorcendo brutalmente o cálculo do Z-Score, Cointegração e ADX (levando a falsas entradas).
- **Solução:** O `timeframe` lido das configurações deve ser convertido de nomenclatura Binance (ex: `1h`, `15m`) para a nomenclatura de offsets do Pandas (`1H`, `15min`) e passado explicitamente para o construtor do `date_range`.

### 4. Perda do "High Water Mark" do Circuit Breaker Global
- **Local:** `main.py` (linhas 159 e 172)
- **Problema:** O `INITIAL_EQUITY` atua como um Trailing Stop (Sobe junto com o capital, mas não desce). No entanto, o pico histórico vive apenas na memória RAM da aplicação.
- **Consequência:** Se o seu bot cair, travar ou o contêiner for reiniciado, o robô recalcula o `INITIAL_EQUITY` com base no saldo daquele momento. Todo o Trailing Stop conquistado será resetado.
- **Solução:** Salvar o Peak Equity diretamente no SQLite persistente toda vez que ele for renovado.

### 5. Polling Excessivo e Concorrência Pobre no SQLite
- **Local:** `database.py` e `main.py` (linhas 35-41)
- **Problema:** Dentro do loop em `main.py`, a função `get_config_async` é chamada repetidas vezes (para ler alvos, stops e limits) a cada *ciclo de segundos* para *cada par*. 
- **Consequência:** Com 5 pares operando, isso pode gerar 50 a 100 queries de I/O em disco por minuto. Apesar de usar modo WAL e `to_thread`, isso causa micro-gargalos e potencial para erros `database is locked`.
- **Solução:** Migrar a leitura do SQLite para a biblioteca nativa assíncrona `aiosqlite`, e implementar um *cache em memória* (ex: Dicionário Global) que atualiza com o banco apenas a cada 60 segundos ou através de eventos.

### 6. Congelamento da Interface Web (Scanner Síncrono)
- **Local:** `scanner.py` (linha 60) e `dashboard.py` (linha 249)
- **Problema:** A função `run_market_scan` utiliza `requests.get()` (síncrono) com `time.sleep(0.3)`. 
- **Consequência:** Quando disparado no Streamlit, a aba do usuário fica totalmente travada (sem interatividade) por 20+ segundos enquanto processa os 36 pares listados.
- **Solução:** Converter `scanner.py` para utilizar `aiohttp` com chamadas paralelas (`asyncio.gather`), reduzindo o tempo do scan de 20 segundos para 2 ou 3 segundos.

---

## 🚀 Upgrade Points (Evolução HFT Institucional)

### A. Substituição de REST API por Binance WebSockets
Atualmente o robô busca as velas (klines) de cada par a cada N segundos via REST (`get_klines`).
**Upgrade:** Implementar Websockets (Kline/Candlestick Stream) mantendo um buffer local de velas em memória. Isso:
1. Elimina as chances de Banimento por IP (Rate Limiting).
2. Traz a latência de tomada de decisão para milissegundos.
3. Permite agir no instante exato que o Z-Score rompe o limite, e não após 3 segundos no próximo ciclo do while.

### B. Gestão de Risco Anti-Slippage (Leg Risk)
Ao executar uma arbitragem estatística (Long A / Short B), enviar duas ordens Market consecutivas (`res_b` -> `res_a`) embute um risco direcional grave. Se o ativo B executa e a API rejeita o ativo A (ex: erro de saldo ou timeout de rede), seu robô fica 100% direcional na perna B.
**Upgrade:** Implementar a lógica "Fill-or-Kill" via API se possível ou utilizar **Ordens IOC (Immediate or Cancel)** como Limit nas pontas do spread do Order Book. Se B não executar por completo, a perna A sequer é iniciada.

### C. Alavancagem Dinâmica e Kelly Criterion (Dimensionamento)
Você possui o nocional (exposure) setado como `$6.00` travado.
**Upgrade:** Implementar um cálculo de dimensionamento automático usando a Volatilidade Implícita (ATR) das últimas velas ou Critério de Kelly. Pares com moedas hiper voláteis recebem menos nocional, e pares estáveis recebem mais margem para capturar pequenos desvios.

### D. Variável de Ambiente para Produção
**Upgrade:** Em `exchange.py` (linha 20), o argumento `testnet=True` está chumbado no código (hardcoded). Para trocar entre simulação e dinheiro real, é preciso reescrever o código. Substitua por:
```python
is_testnet = os.getenv("USE_TESTNET", "True").lower() == "true"
self.client = await AsyncClient.create(self.api_key, self.api_secret, testnet=is_testnet)
```

### E. Remodelação Visual do Streamlit (UI/UX)
**Upgrade:** O Dashboard atual mostra apenas os indicadores do último par scaneado. Deve ser estruturado para iterar e gerar múltiplos cards métricos. Com o Streamlit fragment (st.fragment), podemos atualizar APENAS a sessão dos gráficos sem dar refresh na página inteira, dando a fluidez de um terminal de trading profissional.

---

> [!IMPORTANT]
> A recomendação inicial é resolver os **Bugs Críticos 1, 2, 3 e 4**, pois eles podem gerar perdas reais ou comportamento errático de tela caso múltiplos pares sejam listados na sua variável de configuração.

Posso iniciar as correções por componente ou focar em um bug específico. Como deseja prosseguir com a implementação?
