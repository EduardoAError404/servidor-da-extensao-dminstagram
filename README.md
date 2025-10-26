# Servidor da Extensão DM Instagram

Este é o código do servidor **backend** para a extensão de envio em massa de DM do Instagram. Ele utiliza a biblioteca `instagrapi` (API privada) e o framework Flask para expor um endpoint de envio de mensagens.

## Funcionalidades Principais

*   **Autenticação por Session ID:** Usa o cookie `sessionid` para autenticar, evitando o login direto com usuário/senha.
*   **Persistência de Sessão:** Salva o estado da sessão em `session.json` após o primeiro uso, o que é crucial para o anti-bloqueio.
*   **Proxy Configurado:** Suporte a proxy SOCKS5 com autenticação para manter a consistência de IP.
*   **Anti-Bloqueio:** Implementa *Rate Limiting* aleatório (5 a 15 segundos) entre os envios.
*   **CORS Ativado:** Permite a comunicação segura com a extensão do navegador.

## Configuração (Pré-Implantação)

1.  **Crie o arquivo `.env`:** O arquivo `.env` já está no projeto, mas você deve **preenchê-lo** com suas credenciais.

    ```bash
    # Exemplo do conteúdo do .env
    # ATENÇÃO: O valor do SESSION_ID abaixo é um exemplo e está expirado.
    SESSION_ID="SEU_SESSION_ID_AQUI" 
    PROXY="socks5://USUARIO:SENHA@IP:PORTA" 
    FLASK_APP=app.py
    FLASK_ENV=production
    ```

2.  **Atualize o `SESSION_ID`:** Obtenha o `sessionid` mais recente e válido do seu navegador e substitua o valor no `.env`.

3.  **Atualize o `PROXY`:** Configure o `PROXY` no formato `socks5://USUARIO:SENHA@IP:PORTA`.

## Implantação

Recomendamos o uso de um servidor VPS (como DigitalOcean ou AWS) e um gerenciador de processos (como Gunicorn/Supervisor) para manter o servidor rodando em produção.

1.  **Instalar Dependências:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Iniciar o Servidor (Recomendado para Produção):**
    Use um servidor WSGI como Gunicorn.
    ```bash
    gunicorn -w 4 app:app
    ```

3.  **Endpoint do Servidor:**
    *   **Envio de DM:** `http://SEU_IP_OU_DOMINIO:PORTA/send_dm` (Método POST)
    *   **Teste de Status:** `http://SEU_IP_OU_DOMINIO:PORTA/test` (Método GET)

## Próximo Passo

Após a implantação, você deve **editar a linha 10 do `content-script.js`** da sua extensão para apontar para o URL do seu servidor permanente.

