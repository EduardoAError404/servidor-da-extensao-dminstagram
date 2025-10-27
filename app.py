import os
import json
import time
import random
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS
from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired, 
    RateLimitError, 
    ChallengeRequired, 
    TwoFactorRequired,

    FeedbackRequired
)
from dotenv import load_dotenv

# Força o flush do stdout para os logs aparecerem no Gunicorn
sys.stdout = sys.stderr

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

app = Flask(__name__)
CORS(app) # Adiciona suporte a CORS para todas as rotas e origens

# --- Configuração do Cliente InstaAPI ---

# Inicializa o cliente globalmente (será configurado na primeira requisição)
cl = None

def get_instagrapi_client():
    """
    Retorna o cliente InstaAPI, autenticando se necessário.
    """
    global cl
    
    # Se o cliente já estiver autenticado, retorna
    if cl and cl.is_logged_in:
        return cl

    # Configura o cliente
    cl = Client()
    
    print("=" * 50, flush=True)
    print("Iniciando autenticação do Instagram...", flush=True)
    
    # Configurações de Anti-Bloqueio
    # 1. User-Agent: O InstaAPI usa um User-Agent móvel legítimo por padrão.
    # 2. Proxy: Se o PROXY estiver definido no .env, será usado.
    proxy = os.getenv("PROXY")
    if proxy:
        print(f"Configurando proxy: {proxy}", flush=True)
        try:
            cl.set_proxy(proxy)
            print(f"Proxy configurado com sucesso!", flush=True)
        except Exception as e:
            print(f"ERRO ao configurar proxy: {e}", flush=True)
    else:
        print("Nenhum proxy configurado.", flush=True)

    # 3. Persistência de Sessão (Opcional, mas recomendado para produção)
    # cl.dump_settings("session.json") # Para salvar
    # cl.load_settings("session.json") # Para carregar
    
    # Autenticação via Session ID
    session_id = os.getenv("SESSION_ID")
    if not session_id:
        print("ERRO: SESSION_ID não configurado!", flush=True)
        raise ValueError("SESSION_ID não configurado no arquivo .env. Por favor, configure.")
    
    print(f"SESSION_ID encontrado: {session_id[:20]}...", flush=True)

    # 3. Persistência de Sessão: Tenta carregar a sessão salva
    session_file = "session.json" # Arquivo genérico, pois não temos o username
    if os.path.exists(session_file):
        cl.load_settings(session_file)
        print(f"Sessão carregada de {session_file}")

    try:
        # Autentica usando login_by_sessionid (método correto do instagrapi)
        print("Autenticando com SESSION_ID...", flush=True)
        cl.login_by_sessionid(session_id)
        print("\u2705 Autenticação bem-sucedida!", flush=True)
        
        # Verifica se o sessionid é válido fazendo uma requisição real
        try:
            print("Obtendo informações da conta...", flush=True)
            account_info = cl.account_info()
            print(f"\u2705 Usuário autenticado: {account_info.username} (ID: {account_info.pk})", flush=True)
        except Exception as e:
            print(f"\u274c Erro ao obter account_info: {type(e).__name__}: {e}", flush=True)
            raise LoginRequired("Falha ao verificar autenticação. O SESSION_ID pode ter expirado.")
        
        # Salva a sessão para uso futuro (Anti-Bloqueio)
        cl.dump_settings(session_file)
        
        print("Cliente InstaAPI autenticado com sucesso via SESSION_ID. Sessão salva.", flush=True)
        print("=" * 50, flush=True)
        return cl

    except (LoginRequired, ChallengeRequired, TwoFactorRequired, Exception) as e:
        print(f"\u274c ERRO DE AUTENTICAÇÃO: {type(e).__name__}: {e}", flush=True)
        print("=" * 50, flush=True)
        cl = None # Limpa o cliente para forçar nova tentativa
        raise ConnectionError(f"Falha na autenticação do InstaAPI: {e}")

# --- Endpoint de Envio de DM ---

@app.route('/send_dm', methods=['POST'])
def send_dm():
    """
    Endpoint para receber a requisição de envio de DM da extensão.
    """
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "Requisição JSON inválida."}), 400

    username = data.get('username')
    message = data.get('message')
    delay_min = data.get('delay_min', 5)  # Padrão: 5 segundos
    delay_max = data.get('delay_max', 15)  # Padrão: 15 segundos

    if not username or not message:
        return jsonify({"success": False, "error": "Campos 'username' e 'message' são obrigatórios."}), 400

    try:
        # 1. Obtém o cliente autenticado
        client = get_instagrapi_client()
        
        # 2. Obtém o ID do usuário (InstaAPI trabalha com User IDs, não usernames)
        # Este passo é crucial e deve ser feito com cuidado para evitar banimento por spam de busca.
        try:
            user_id = client.user_id_from_username(username)
        except Exception as e:
            print(f"Erro ao buscar User ID para {username}: {e}")
            # Se o usuário não for encontrado, retorna um erro específico
            return jsonify({"success": False, "error": f"Usuário @{username} não encontrado ou erro na busca."}), 404

        # 3. Envio da Mensagem
        # O InstaAPI envia a DM para o User ID
        client.direct_send(text=message, user_ids=[user_id])
        
        # 4. Implementação de Rate Limiting (Anti-Bloqueio)
        # Usa os delays configurados pela extensão
        delay = random.randint(delay_min, delay_max)
        print(f"DM enviada para @{username}. Aguardando {delay} segundos (Rate Limit) antes de finalizar a requisição.")
        time.sleep(delay)

        return jsonify({"success": True, "username": username, "message": message, "delay": delay}), 200

    except RateLimitError as e:
        # Erro de Rate Limit: Parar o processo e avisar o usuário
        print(f"ERRO CRÍTICO (Rate Limit): {e}")
        return jsonify({"success": False, "error": "Limite de taxa atingido. Por favor, espere algumas horas antes de tentar novamente.", "details": str(e)}), 429
    
    except (LoginRequired, ChallengeRequired, TwoFactorRequired) as e:
        # Erro de Autenticação/Segurança: O session_id expirou ou o Instagram pediu verificação
        print(f"ERRO CRÍTICO (Autenticação): {e}")
        # Limpa o cliente para forçar nova autenticação na próxima requisição
        global cl
        cl = None 
        return jsonify({"success": False, "error": "Sessão expirada ou verificação de segurança necessária. Atualize o SESSION_ID no .env.", "details": str(e)}), 401
    
    except FeedbackRequired as e:
        # Erro de Feedback (geralmente acontece após enviar muitas mensagens iguais)
        print(f"ERRO CRÍTICO (Feedback): {e}")
        return jsonify({"success": False, "error": "Feedback de spam recebido. O Instagram bloqueou temporariamente o envio de mensagens.", "details": str(e)}), 403
        
    except ConnectionError as e:
        # Erro de Conexão (geralmente falha na autenticação inicial)
        return jsonify({"success": False, "error": str(e)}), 500

    except Exception as e:
        # Qualquer outro erro não previsto
        print(f"Erro inesperado: {e}")
        return jsonify({"success": False, "error": f"Erro interno do servidor: {type(e).__name__}", "details": str(e)}), 500

# Endpoint de Teste
@app.route('/test', methods=['GET'])
def test_route():
    return jsonify({"status": "Servidor InstaDM Online", "client_status": cl.is_logged_in if cl else "Not Initialized"}), 200

if __name__ == '__main__':
    # Tenta inicializar o cliente na inicialização
    try:
        get_instagrapi_client()
    except Exception as e:
        print(f"Aviso: Não foi possível autenticar na inicialização. O servidor tentará novamente na primeira requisição. Erro: {e}")
        
    # O servidor deve rodar em 0.0.0.0 para ser acessível pelo expose
    app.run(host='0.0.0.0', port=5001, debug=False)

