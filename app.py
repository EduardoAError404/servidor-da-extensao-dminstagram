import os
import json
import time
import random
import sys
import threading
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

print("="*60, flush=True)
print("🚀 INICIANDO SERVIDOR INSTADM", flush=True)
print("="*60, flush=True)

# Debug: Verificar se variáveis de ambiente estão disponíveis
session_id_check = os.getenv('SESSION_ID')
proxy_check = os.getenv('PROXY')
flask_env_check = os.getenv('FLASK_ENV')

print(f"🔍 Verificando variáveis de ambiente:", flush=True)
print(f"   SESSION_ID: {'✅ Configurado' if session_id_check else '❌ NÃO ENCONTRADO'}", flush=True)
if session_id_check:
    print(f"   SESSION_ID (primeiros 20 chars): {session_id_check[:20]}...", flush=True)
print(f"   PROXY: {'✅ Configurado' if proxy_check else '❌ NÃO ENCONTRADO'}", flush=True)
if proxy_check:
    print(f"   PROXY: {proxy_check}", flush=True)
print(f"   FLASK_ENV: {flask_env_check or 'não configurado'}", flush=True)
print("="*60, flush=True)

app = Flask(__name__)
CORS(app) # Adiciona suporte a CORS para todas as rotas e origens

# --- Configuração do Cliente InstaAPI ---

# Inicializa o cliente globalmente (será configurado na primeira requisição)
cl = None
# Lock para evitar que múltiplos workers tentem fazer login ao mesmo tempo
login_lock = threading.Lock()

def get_instagrapi_client():
    """
    Retorna o cliente InstaAPI, usando persistência de sessão.
    IMPORTANTE: NÃO faz login a cada requisição, apenas carrega a sessão salva.
    """
    global cl
    
    session_file = "/tmp/instagram_session.json"
    
    # Se o cliente já estiver autenticado, retorna
    if cl:
        try:
            # Verifica se ainda está autenticado fazendo uma requisição rápida
            cl.account_info()
            return cl
        except:
            # Se falhar, tenta recarregar a sessão
            print("⚠️ Sessão expirada, recarregando...", flush=True)
            cl = None

    # Usa lock para evitar que múltiplos workers tentem fazer login ao mesmo tempo
    with login_lock:
        # Verifica novamente se outro worker já autenticou enquanto esperávamos o lock
        if cl:
            try:
                cl.account_info()
                return cl
            except:
                cl = None
        
        # Configura o cliente
        cl = Client()
        
        print("=" * 50, flush=True)
        print("Carregando sessão do Instagram...", flush=True)
        
        # Configurações de Anti-Bloqueio
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

        # Tenta carregar a sessão salva
        if os.path.exists(session_file):
            try:
                print(f"Carregando sessão de {session_file}...", flush=True)
                cl.load_settings(session_file)
                print("✅ Sessão carregada com sucesso!", flush=True)
                
                # Verifica se a sessão ainda é válida
                try:
                    account_info = cl.account_info()
                    print(f"✅ Sessão válida! Usuário: {account_info.username} (ID: {account_info.pk})", flush=True)
                    print("=" * 50, flush=True)
                    return cl
                except LoginRequired:
                    print("⚠️ Sessão expirada, fazendo novo login...", flush=True)
                    cl = Client()  # Recria o cliente
                    if proxy:
                        cl.set_proxy(proxy)
            except Exception as e:
                print(f"⚠️ Erro ao carregar sessão: {e}", flush=True)
                cl = Client()  # Recria o cliente
                if proxy:
                    cl.set_proxy(proxy)
        
        # Se não conseguiu carregar a sessão, faz login com SESSION_ID
        session_id = os.getenv("SESSION_ID")
        if not session_id:
            print("ERRO: SESSION_ID não configurado!", flush=True)
            raise ValueError("SESSION_ID não configurado no arquivo .env. Por favor, configure.")
        
        print(f"SESSION_ID encontrado: {session_id[:20]}...", flush=True)

        try:
            # Autentica usando login_by_sessionid (método correto do instagrapi)
            print("Autenticando com SESSION_ID...", flush=True)
            cl.login_by_sessionid(session_id)
            print("✅ Autenticação bem-sucedida!", flush=True)
            
            # Verifica se o sessionid é válido
            account_info = cl.account_info()
            print(f"✅ Usuário autenticado: {account_info.username} (ID: {account_info.pk})", flush=True)
            
            # Salva a sessão para uso futuro
            print(f"Salvando sessão em {session_file}...", flush=True)
            cl.dump_settings(session_file)
            print("✅ Sessão salva com sucesso!", flush=True)
            
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
        
        # 4. Retorna sucesso com delay recomendado
        # O delay será aplicado pela EXTENSÃO, não pelo servidor
        # Isso evita timeout do Gunicorn
        delay = random.randint(delay_min, delay_max)
        print(f"✅ DM enviada para @{username}. Delay recomendado: {delay}s", flush=True)

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
    try:
        # Tenta obter/autenticar o cliente
        client = get_instagrapi_client()
        
        # Verifica se está autenticado fazendo uma requisição real
        try:
            account_info = client.account_info()
            return jsonify({
                "status": "Servidor InstaDM Online",
                "client_status": "Authenticated",
                "username": account_info.username,
                "user_id": str(account_info.pk)
            }), 200
        except Exception as e:
            return jsonify({
                "status": "Servidor InstaDM Online",
                "client_status": "Authentication Failed",
                "error": str(e)
            }), 200
    except Exception as e:
        return jsonify({
            "status": "Servidor InstaDM Online",
            "client_status": "Not Initialized",
            "error": str(e)
        }), 200

# Tenta inicializar o cliente automaticamente quando o módulo é carregado
print("\n" + "="*60, flush=True)
print("🔑 Tentando autenticar automaticamente...", flush=True)
print("="*60, flush=True)
try:
    get_instagrapi_client()
    print("✅ Autenticação automática bem-sucedida!", flush=True)
except Exception as e:
    print(f"⚠️ Aviso: Autenticação automática falhou. O servidor tentará novamente na primeira requisição.", flush=True)
    print(f"   Erro: {type(e).__name__}: {e}", flush=True)
print("="*60 + "\n", flush=True)

if __name__ == '__main__':
    # O servidor deve rodar em 0.0.0.0 para ser acessível pelo expose
    app.run(host='0.0.0.0', port=5001, debug=False)

