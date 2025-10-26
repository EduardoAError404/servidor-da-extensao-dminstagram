import os
import json
import time
import random
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
    
    # Configurações de Anti-Bloqueio
    # 1. User-Agent: O InstaAPI usa um User-Agent móvel legítimo por padrão.
    # 2. Proxy: Se o PROXY estiver definido no .env, será usado.
    proxy = os.getenv("PROXY")
    if proxy:
        cl.set_proxy(proxy)
        print(f"Proxy configurado: {proxy}")

    # 3. Persistência de Sessão (Opcional, mas recomendado para produção)
    # cl.dump_settings("session.json") # Para salvar
    # cl.load_settings("session.json") # Para carregar
    
    # Autenticação via Session ID
    session_id = os.getenv("SESSION_ID")
    if not session_id:
        raise ValueError("SESSION_ID não configurado no arquivo .env. Por favor, configure.")

    # 3. Persistência de Sessão: Tenta carregar a sessão salva
    session_file = "session.json" # Arquivo genérico, pois não temos o username
    if os.path.exists(session_file):
        cl.load_settings(session_file)
        print(f"Sessão carregada de {session_file}")

    try:
        # Tenta setar o sessionid. Se for um sessionid válido, a autenticação deve ser bem-sucedida.
        cl.set_sessionid(session_id)
        
        if not cl.is_logged_in:
            # Se falhar, o sessionid pode ter expirado.
            raise LoginRequired("Falha ao autenticar com o SESSION_ID fornecido. O ID pode ter expirado.")
        
        # Salva a sessão para uso futuro (Anti-Bloqueio)
        cl.dump_settings(session_file)
        
        print("Cliente InstaAPI autenticado com sucesso via SESSION_ID. Sessão salva.")
        return cl

    except (LoginRequired, ChallengeRequired, TwoFactorRequired, Exception) as e:
        print(f"Erro de autenticação: {e}")
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
        # Espera um tempo aleatório entre 5 e 15 segundos antes de retornar o sucesso
        delay = random.randint(5, 15)
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

