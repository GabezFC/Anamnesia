"""Central de Importação, Exportação e Inicialização do Workspace.

Camadas (nada aqui executa comandos nem abre terminais):
  gitignore  -> matcher de .gitignore (sem dependência externa)
  scanner    -> varredura segura de um projeto (ignora segredos, binários, enormes, node_modules...)
  jobs       -> tarefas em segundo plano com progresso e cancelamento cooperativo
  tasks      -> inicialização/indexação, importação e exportação (reaproveita app.memory_store e os serviços de custo)
"""
