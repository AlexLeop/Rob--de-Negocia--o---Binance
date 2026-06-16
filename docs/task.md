# Tarefas de Implementação: Upgrades HFT e Resiliência

- [x] Criar `api_health.py`
- [x] Modificar `config.py` e `.env` (TESTNET, R:R Target $1.50 / Stop $1.00 / Amount $30.0)
- [x] Modificar `database.py` para refletir os novos defaults (R:R e Trade Amount)
- [x] Atualizar `exchange.py`
  - Instanciar `ApiHealthTracker`
  - Utilizar variável `TESTNET`
  - Envolver chamadas em `try/except` para registrar health
  - Corrigir Bug B: ignorar a vela atual em formação (`.iloc[:-1]`)
- [x] Atualizar `strategy.py`
  - Implementar e utilizar `rolling_beta_vectorized`
- [x] Refatorar `main.py`
  - Adicionar `auto_scan_pairs()` com checagem de posições encalhadas (> 4h)
  - Criar `supervisor_par`
  - Reordenar loop em `monitorar_par` (buscar `is_open` antes do health check)
  - Corrigir Bug A (evitar repetição de sinal na mesma vela via `current_candle_ts`)
  - Limpar exceções com `safe_close_pair` se `in_critical_section` estiver True
- [x] Verificar alterações e documentar o processo no `walkthrough.md`
