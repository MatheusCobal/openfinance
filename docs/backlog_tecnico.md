# Backlog tecnico

## Teste de conciliacao manual de custo fixo

- Validar no frontend o fluxo de marcar uma transacao da fatura como pagamento de um custo fixo.
- Cenario esperado: a transacao continua compondo a fatura do cartao, o custo fixo fica como pago no mes e o valor deixa de consumir a meta variavel da categoria original.
- Cenario de regressao backend coberto em `tests/test_fixed_costs.py`: `test_manual_fixed_cost_match_keeps_invoice_and_skips_variable_budget`.
