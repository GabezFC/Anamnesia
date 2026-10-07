# Segurança do dashboard (S6): Content-Security-Policy

`app/main.py::_security_headers` envia em todas as respostas (exceto `/docs`, `/redoc`, `/openapi.json`, que carregam
Swagger/ReDoc de CDN):

`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`

- Sem `'unsafe-inline'`/`'unsafe-eval'` em scripts: HTML injetado via conteúdo de nota/resposta do modelo não executa JS,
  então não consegue ler o token de escrita local.
- `style-src 'unsafe-inline'` é necessário: a UI usa atributos `style="..."` (barras, cores). Isso é só CSS; mitigar
  exfiltração por CSS exigiria migrar para classes (não feito).
- O frontend não carrega nada externo (sem CDN, fontes ou imagens remotas).
- Regra de código: todo dado vindo da API entra em templates `innerHTML` via `esc()` (`frontend/js/format.js`).
  `tests/test_csp.py` cobre o header e uma checagem estática simples.
