#!/usr/bin/env python3
"""
Sistema Distribuído de Controle de Semáforos - Servidor de Logs
=====================================================================
Implementação Acadêmica: Servidor passivo que apenas registra eventos
Não participa da lógica de sincronização distribuída

Uso:
    python logger_server.py [--host HOST] [--port PORT]
    
Exemplo:
    python logger_server.py --host 0.0.0.0 --port 9000
"""

import socket
import threading
import json
import time
import sys
import argparse
from datetime import datetime


class LoggerServer:
    """
    Servidor de Logs Passivo - Painel de Controle Central
    
    Este servidor NÃO participa do algoritmo de exclusão mútua.
    Ele apenas recebe notificações de mudança de estado dos semáforos
    e as exibe no console, funcionando como um painel de monitoramento.
    """
    
    def __init__(self, host='0.0.0.0', port=9000):
        self.host = host
        self.port = port
        self.running = False
        self.server_socket = None
        
    def start(self):
        """Inicia o servidor de logs"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(10)
            self.running = True
            
            print("="*70)
            print("SERVIDOR DE LOGS - PAINEL DE CONTROLE DE SEMÁFOROS")
            print("="*70)
            print(f"Escutando em {self.host}:{self.port}")
            print(f"Aguardando conexões de nós de semáforo...")
            print("="*70)
            print()
            
            # Loop principal: aceita conexões de clientes
            while self.running:
                try:
                    client_socket, client_address = self.server_socket.accept()
                    # Cria uma thread para lidar com cada cliente
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, client_address),
                        daemon=True
                    )
                    client_thread.start()
                except Exception as e:
                    if self.running:
                        print(f"[ERRO] Erro ao aceitar conexão: {e}")
                        
        except Exception as e:
            print(f"[ERRO FATAL] Não foi possível iniciar o servidor: {e}")
            sys.exit(1)
            
    def handle_client(self, client_socket, client_address):
        """
        Trata mensagens de um cliente específico
        
        Cada nó de semáforo se conecta e envia mensagens de log.
        O formato esperado é JSON: {"method": "log_event", "args": {...}}
        """
        print(f"[CONEXÃO] Nova conexão de {client_address}")
        
        buffer = ""
        
        try:
            while self.running:
                # Recebe dados do socket
                data = client_socket.recv(4096)
                if not data:
                    break
                    
                buffer += data.decode('utf-8')
                
                # Processa todas as mensagens completas no buffer
                # Mensagens são separadas por newline
                while '\n' in buffer:
                    message, buffer = buffer.split('\n', 1)
                    if message.strip():
                        self.process_message(message.strip(), client_address)
                        
        except Exception as e:
            print(f"[ERRO] Erro ao processar cliente {client_address}: {e}")
        finally:
            client_socket.close()
            print(f"[DESCONEXÃO] Cliente {client_address} desconectado")
            
    def process_message(self, message, client_address):
        """
        Processa uma mensagem de log recebida
        
        Esta é a implementação do "RPC Manual" no lado do servidor.
        Desserializa o JSON e despacha para o método apropriado.
        """
        try:
            # Desserialização (Unmarshal) da mensagem JSON
            msg_obj = json.loads(message)
            
            method = msg_obj.get('method', '')
            args = msg_obj.get('args', {})
            
            # Despacho de método (Method Dispatch)
            if method == 'log_event':
                self.log_event(args, client_address)
            else:
                print(f"[AVISO] Método desconhecido: {method}")
                
        except json.JSONDecodeError as e:
            print(f"[ERRO] Mensagem JSON inválida de {client_address}: {e}")
        except Exception as e:
            print(f"[ERRO] Erro ao processar mensagem: {e}")
            
    def log_event(self, args, client_address):
        """
        Registra um evento de mudança de estado de semáforo
        
        Args esperados:
            - node_id: identificador do nó
            - state: novo estado (RED, YELLOW, GREEN)
            - timestamp: timestamp lógico (Lamport)
            - message: mensagem adicional
        """
        node_id = args.get('node_id', 'UNKNOWN')
        state = args.get('state', 'UNKNOWN')
        logical_time = args.get('timestamp', 0)
        msg = args.get('message', '')
        
        # Formata a saída com cores ANSI para melhor visualização
        color_code = {
            'RED': '\033[91m',      # Vermelho
            'YELLOW': '\033[93m',   # Amarelo
            'GREEN': '\033[92m',    # Verde
        }.get(state, '\033[0m')
        
        reset_code = '\033[0m'
        
        timestamp_str = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        
        print(f"[{timestamp_str}] [{node_id}] [L={logical_time}] "
              f"{color_code}{state:6}{reset_code} | {msg}")
              
    def stop(self):
        """Para o servidor"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()


def main():
    """Função principal"""
    parser = argparse.ArgumentParser(
        description='Servidor de Logs para Sistema de Semáforos Distribuído'
    )
    parser.add_argument('--host', type=str, default='0.0.0.0',
                       help='Host do servidor (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=9000,
                       help='Porta do servidor (default: 9000)')
    
    args = parser.parse_args()
    
    server = LoggerServer(host=args.host, port=args.port)
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n\n[INFO] Encerrando servidor...")
        server.stop()
        print("[INFO] Servidor encerrado.")


if __name__ == '__main__':
    main()