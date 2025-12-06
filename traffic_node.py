#!/usr/bin/env python3
"""
Sistema Distribuído de Controle de Semáforos - Nó de Semáforo
==============================================================
Implementação Acadêmica com:
- RPC Manual sobre TCP/IP
- Relógios Lógicos de Lamport
- Algoritmo de Ricart-Agrawala para Exclusão Mútua

Uso:
    python traffic_node.py --id NODE_ID --host HOST --port PORT 
                          --peers PEER1,PEER2,... --logger LOGGER_ADDR
    
Exemplo:
    # Nó 1
    python traffic_node.py --id Node1 --host 127.0.0.1 --port 5001 \\
        --peers 127.0.0.1:5002,127.0.0.1:5003 --logger 127.0.0.1:9000
    
    # Nó 2
    python traffic_node.py --id Node2 --host 127.0.0.1 --port 5002 \\
        --peers 127.0.0.1:5001,127.0.0.1:5003 --logger 127.0.0.1:9000
"""

import socket
import threading
import json
import time
import sys
import argparse
import random


# =============================================================================
# RELÓGIOS LÓGICOS DE LAMPORT
# =============================================================================

class LamportClock:
    """
    Implementação dos Relógios Lógicos de Lamport
    
    Regras de Lamport:
    1. Inicialmente L = 0
    2. Antes de um evento local: L = L + 1
    3. Ao enviar mensagem: anexa L à mensagem
    4. Ao receber mensagem com timestamp T: L = max(L, T) + 1
    
    Esta implementação garante a ordenação causal de eventos no sistema.
    """
    
    def __init__(self):
        self.time = 0
        self.lock = threading.Lock()  # Protege acesso concorrente ao relógio
        
    def tick(self):
        """
        Incrementa o relógio para um evento local
        Regra: L = L + 1
        """
        with self.lock:
            self.time += 1
            return self.time
            
    def send_time(self):
        """
        Obtém o timestamp para enviar em uma mensagem
        Automaticamente incrementa o relógio (evento de envio)
        """
        return self.tick()
        
    def receive_time(self, received_time):
        """
        Atualiza o relógio ao receber uma mensagem
        Regra de Lamport: L = max(L, T) + 1
        
        Args:
            received_time: timestamp recebido na mensagem
        """
        with self.lock:
            self.time = max(self.time, received_time) + 1
            return self.time
            
    def get_time(self):
        """Retorna o tempo lógico atual (sem incrementar)"""
        with self.lock:
            return self.time


# =============================================================================
# CAMADA DE COMUNICAÇÃO - RPC MANUAL
# =============================================================================

class NodeComms:
    """
    Camada de Comunicação com RPC Manual sobre TCP
    
    Esta classe implementa um mecanismo de RPC (Remote Procedure Call) 
    construído do zero sobre sockets TCP. Não usa bibliotecas prontas.
    
    Protocolo:
    - Mensagens são serializadas em JSON
    - Formato: {"method": "nome_funcao", "args": {...}, "clock": timestamp}
    - Mensagens terminam com '\n' (newline) como delimitador
    - Ao receber, faz unmarshal e despacha para o handler apropriado
    """
    
    def __init__(self, host, port, message_handler):
        self.host = host
        self.port = port
        self.message_handler = message_handler  # Callback para processar mensagens
        self.server_socket = None
        self.running = False
        
    def start_server(self):
        """Inicia o servidor RPC que escuta conexões de outros nós"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True
        
        # Thread para aceitar conexões
        accept_thread = threading.Thread(target=self._accept_connections, daemon=True)
        accept_thread.start()
        
    def _accept_connections(self):
        """Loop que aceita conexões de outros nós"""
        while self.running:
            try:
                client_socket, client_address = self.server_socket.accept()
                # Cada conexão é tratada em uma thread separada
                handler_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket,),
                    daemon=True
                )
                handler_thread.start()
            except Exception as e:
                if self.running:
                    print(f"[COMMS] Erro ao aceitar conexão: {e}")
                    
    def _handle_client(self, client_socket):
        """
        Trata mensagens RPC recebidas de um cliente
        
        Esta é a parte de "unmarshaling" e "method dispatch" do RPC manual.
        """
        buffer = ""
        
        try:
            while self.running:
                data = client_socket.recv(4096)
                if not data:
                    break
                    
                buffer += data.decode('utf-8')
                
                # Processa mensagens completas (delimitadas por '\n')
                while '\n' in buffer:
                    message, buffer = buffer.split('\n', 1)
                    if message.strip():
                        self._process_rpc_message(message.strip())
                        
        except Exception as e:
            pass  # Conexão fechada
        finally:
            client_socket.close()
            
    def _process_rpc_message(self, message):
        """
        Desserializa e despacha uma mensagem RPC
        
        [RPC MANUAL - UNMARSHALING E DISPATCH]
        1. Desserializa JSON
        2. Extrai o nome do método
        3. Despacha para o handler registrado
        """
        try:
            msg_obj = json.loads(message)
            method = msg_obj.get('method', '')
            args = msg_obj.get('args', {})
            clock = msg_obj.get('clock', 0)
            
            # Despacha para o handler (que vai processar conforme o método)
            self.message_handler(method, args, clock)
            
        except Exception as e:
            print(f"[COMMS] Erro ao processar mensagem RPC: {e}")
            
    def send_rpc(self, peer_address, method, args, clock_time, timeout=3.0, max_retries=3):
        """
        Envia uma chamada RPC para um peer com retry
        
        [RPC MANUAL - MARSHALING E ENVIO]
        1. Serializa os dados em JSON
        2. Envia via socket TCP
        3. Retry automático em caso de falha
        
        Args:
            peer_address: tupla (host, port) do destino
            method: nome do método remoto a chamar
            args: argumentos do método (dict)
            clock_time: timestamp lógico de Lamport
            timeout: timeout da conexão
            max_retries: número máximo de tentativas
        
        Returns:
            True se sucesso, False se falha
        """
        for attempt in range(max_retries):
            try:
                # Cria a mensagem RPC no formato JSON
                rpc_message = {
                    "method": method,
                    "args": args,
                    "clock": clock_time
                }
                
                # Serialização (Marshaling)
                message_str = json.dumps(rpc_message) + '\n'
                
                # Estabelece conexão TCP com o peer
                client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client_socket.settimeout(timeout)
                
                client_socket.connect(peer_address)
                client_socket.sendall(message_str.encode('utf-8'))
                client_socket.close()
                
                return True
                
            except (socket.timeout, ConnectionRefusedError, OSError) as e:
                if attempt < max_retries - 1:
                    # Aguarda antes de tentar novamente
                    time.sleep(0.5 * (attempt + 1))
                    continue
                else:
                    # Falhou em todas as tentativas
                    return False
            except Exception as e:
                return False
        
        return False
    
    def check_peer_available(self, peer_address, timeout=1.0):
        """
        Verifica se um peer está disponível (escutando)
        
        Args:
            peer_address: tupla (host, port)
            timeout: timeout da tentativa
            
        Returns:
            True se peer está disponível, False caso contrário
        """
        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(timeout)
            test_socket.connect(peer_address)
            test_socket.close()
            return True
        except:
            return False
            
    def stop(self):
        """Para o servidor"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()


# =============================================================================
# NÓ DE SEMÁFORO - ALGORITMO DE RICART-AGRAWALA
# =============================================================================

class TrafficLight:
    """
    Nó de Semáforo com Exclusão Mútua Distribuída
    
    Implementa o Algoritmo de Ricart-Agrawala para garantir que apenas
    um semáforo esteja VERDE (na seção crítica) por vez.
    
    Estados do Semáforo:
    - RED (Vermelho): Estado padrão
    - YELLOW (Amarelo): Transição
    - GREEN (Verde): Seção Crítica
    
    Estados do Algoritmo:
    - RELEASED: Não quer entrar na seção crítica
    - WANTED: Quer entrar (enviou requisições)
    - HELD: Está na seção crítica
    """
    
    # Estados do semáforo
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    
    # Estados do algoritmo de exclusão mútua
    RELEASED = "RELEASED"
    WANTED = "WANTED"
    HELD = "HELD"
    
    def __init__(self, node_id, host, port, peers, logger_addr):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.peers = peers  # Lista de tuplas (host, port)
        self.logger_addr = logger_addr  # Endereço do servidor de logs
        
        # Relógio Lógico de Lamport
        self.clock = LamportClock()
        
        # Estado do semáforo
        self.light_state = self.RED
        
        # Estado do algoritmo de Ricart-Agrawala
        self.mutex_state = self.RELEASED
        self.request_timestamp = 0  # Timestamp da nossa requisição
        self.replies_received = set()  # Set de peers que responderam
        self.deferred_replies = []  # Fila de nós aguardando resposta
        
        # Lock para proteger estado compartilhado
        self.state_lock = threading.Lock()
        
        # Camada de comunicação (RPC Manual)
        self.comms = NodeComms(host, port, self.handle_rpc_message)
        
    def start(self):
        """Inicia o nó de semáforo"""
        print(f"[{self.node_id}] Iniciando em {self.host}:{self.port}")
        print(f"[{self.node_id}] Peers: {self.peers}")
        
        # Inicia o servidor RPC
        self.comms.start_server()
        
        # Log inicial
        self.log_to_server("Nó iniciado em estado RED")
        
        # CORREÇÃO: Aguarda que todos os peers estejam online
        self.wait_for_peers()
        
        # Inicia o ciclo do semáforo
        self.run_traffic_cycle()
    
    def wait_for_peers(self):
        """
        Aguarda que todos os peers estejam disponíveis
        
        [CORREÇÃO DO RACE CONDITION]
        Esta função garante que não tentaremos enviar requisições
        para peers que ainda não iniciaram seus servidores RPC.
        """
        print(f"\n[{self.node_id}] Aguardando todos os peers ficarem online...")
        
        max_wait = 60  # Máximo 60 segundos
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            all_available = True
            
            for peer in self.peers:
                if not self.comms.check_peer_available(peer, timeout=0.5):
                    all_available = False
                    print(f"[{self.node_id}]   Aguardando peer {peer}...")
                    break
            
            if all_available:
                print(f"[{self.node_id}] ✓ Todos os peers estão online!")
                # Aguarda mais um pouco para garantir estabilidade
                time.sleep(2)
                return
            
            time.sleep(1)
        
        print(f"[{self.node_id}] ⚠ Timeout aguardando peers. Continuando mesmo assim...")
        
    def handle_rpc_message(self, method, args, received_clock):
        """
        Handler central para mensagens RPC recebidas
        
        [SINCRONIZAÇÃO DE LAMPORT]
        Ao receber qualquer mensagem, atualiza o relógio:
        L = max(L, T) + 1
        """
        # Atualiza o relógio de Lamport ao receber mensagem
        self.clock.receive_time(received_clock)
        
        # Despacha para o método apropriado
        if method == "request_access":
            self.handle_request_access(args, received_clock)
        elif method == "reply_ok":
            self.handle_reply_ok(args)
        else:
            print(f"[{self.node_id}] Método desconhecido: {method}")
            
    def handle_request_access(self, args, request_clock):
        """
        Trata uma requisição de acesso à seção crítica
        
        [ALGORITMO DE RICART-AGRAWALA - DECISÃO DE REPLY]
        
        Regras:
        1. Se não estamos interessados (RELEASED): Reply imediatamente
        2. Se já estamos na seção crítica (HELD): Adiciona à fila
        3. Se também queremos (WANTED): Compara timestamps
           - Se timestamp do outro < nosso: Reply imediatamente
           - Se timestamp do outro > nosso: Adiciona à fila
           - Se empate: usa node_id como desempate
        """
        requester_id = args.get('node_id')
        requester_addr = tuple(args.get('address'))
        
        print(f"[{self.node_id}] Requisição recebida de {requester_id} "
              f"(T={request_clock})")
        
        with self.state_lock:
            should_reply = False
            
            if self.mutex_state == self.RELEASED:
                # Não estamos interessados: responde imediatamente
                should_reply = True
                print(f"[{self.node_id}]   -> RELEASED: enviando OK imediato")
                
            elif self.mutex_state == self.HELD:
                # Já estamos na seção crítica: adiciona à fila
                self.deferred_replies.append((requester_id, requester_addr))
                print(f"[{self.node_id}]   -> HELD: adicionando à fila")
                
            elif self.mutex_state == self.WANTED:
                # Ambos querem: compara timestamps (Lamport)
                if request_clock < self.request_timestamp:
                    # Requisição dele é mais antiga: dá prioridade
                    should_reply = True
                    print(f"[{self.node_id}]   -> WANTED: requisição dele é "
                          f"mais antiga ({request_clock} < {self.request_timestamp})")
                elif request_clock > self.request_timestamp:
                    # Nossa requisição é mais antiga: adiciona à fila
                    self.deferred_replies.append((requester_id, requester_addr))
                    print(f"[{self.node_id}]   -> WANTED: nossa requisição é "
                          f"mais antiga ({self.request_timestamp} < {request_clock})")
                else:
                    # Timestamps iguais: usa node_id como desempate
                    if requester_id < self.node_id:
                        should_reply = True
                        print(f"[{self.node_id}]   -> WANTED: desempate por ID")
                    else:
                        self.deferred_replies.append((requester_id, requester_addr))
                        print(f"[{self.node_id}]   -> WANTED: desempate por ID (nossa prioridade)")
        
        # Envia resposta se apropriado
        if should_reply:
            self.send_reply_ok(requester_addr)
            
    def handle_reply_ok(self, args):
        """
        Trata uma resposta OK à nossa requisição
        
        [ALGORITMO DE RICART-AGRAWALA - CONTAGEM DE RESPOSTAS]
        Adiciona o peer ao set de respostas recebidas.
        Quando todas chegarem, pode entrar na seção crítica.
        """
        replier_id = args.get('node_id')
        
        with self.state_lock:
            self.replies_received.add(replier_id)
            print(f"[{self.node_id}] Reply OK de {replier_id} "
                  f"({len(self.replies_received)}/{len(self.peers)})")
            
    def request_critical_section(self):
        """
        Solicita entrada na seção crítica (ficar VERDE)
        
        [ALGORITMO DE RICART-AGRAWALA - REQUISIÇÃO]
        1. Muda estado para WANTED
        2. Incrementa relógio (evento local)
        3. Envia request_access para todos os peers
        4. Aguarda todas as respostas
        """
        with self.state_lock:
            self.mutex_state = self.WANTED
            self.replies_received = set()  # Reset do set
            # [LAMPORT] Evento local: incrementa relógio
            self.request_timestamp = self.clock.tick()
            
        print(f"\n[{self.node_id}] === REQUISITANDO SEÇÃO CRÍTICA "
              f"(T={self.request_timestamp}) ===")
        
        # Envia requisição para todos os peers
        successful_sends = 0
        for peer in self.peers:
            # [LAMPORT] Ao enviar: usa o timestamp
            send_time = self.clock.send_time()
            
            # [RPC MANUAL] Invoca método remoto com retry
            success = self.comms.send_rpc(
                peer,
                method="request_access",
                args={
                    "node_id": self.node_id,
                    "address": (self.host, self.port)
                },
                clock_time=send_time,
                max_retries=3
            )
            
            if success:
                successful_sends += 1
            else:
                print(f"[{self.node_id}] ⚠ Falha ao enviar para {peer}")
        
        print(f"[{self.node_id}] Requisições enviadas: {successful_sends}/{len(self.peers)}")
        print(f"[{self.node_id}] Aguardando {len(self.peers)} respostas...")
        
        # Aguarda todas as respostas com timeout
        max_wait = 30  # 30 segundos máximo
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            with self.state_lock:
                if len(self.replies_received) >= len(self.peers):
                    break
            time.sleep(0.1)
        
        with self.state_lock:
            received = len(self.replies_received)
            
        if received >= len(self.peers):
            print(f"[{self.node_id}] === TODAS AS RESPOSTAS RECEBIDAS ===\n")
        else:
            print(f"[{self.node_id}] ⚠ Timeout: recebidas {received}/{len(self.peers)} respostas")
            print(f"[{self.node_id}] Continuando mesmo assim...")
        
    def enter_critical_section(self):
        """
        Entra na seção crítica (fica VERDE)
        
        [ALGORITMO DE RICART-AGRAWALA - ENTRADA]
        Só é chamado após receber todas as respostas (ou timeout).
        """
        with self.state_lock:
            self.mutex_state = self.HELD
            
        # Transição: RED -> GREEN
        self.change_light_state(self.GREEN)
        
        print(f"[{self.node_id}] *** NA SEÇÃO CRÍTICA (VERDE) ***")
        
        # Permanece verde por um tempo
        green_duration = random.uniform(3, 6)
        time.sleep(green_duration)
        
    def exit_critical_section(self):
        """
        Sai da seção crítica (fica VERMELHO)
        
        [ALGORITMO DE RICART-AGRAWALA - SAÍDA]
        1. Muda estado para RELEASED
        2. Envia reply_ok para todos os nós na fila de espera
        """
        # Transição: GREEN -> YELLOW -> RED
        self.change_light_state(self.YELLOW)
        time.sleep(1)
        self.change_light_state(self.RED)
        
        with self.state_lock:
            self.mutex_state = self.RELEASED
            deferred = self.deferred_replies.copy()
            self.deferred_replies = []
            
        print(f"[{self.node_id}] Saiu da seção crítica. "
              f"Enviando {len(deferred)} respostas diferidas.")
        
        # Envia respostas para todos que estavam aguardando
        for node_id, addr in deferred:
            self.send_reply_ok(addr)
            
    def send_reply_ok(self, peer_addr):
        """Envia uma resposta OK para um peer"""
        # [LAMPORT] Evento de envio
        send_time = self.clock.send_time()
        
        # [RPC MANUAL] Invoca método remoto com retry
        success = self.comms.send_rpc(
            peer_addr,
            method="reply_ok",
            args={"node_id": self.node_id},
            clock_time=send_time,
            max_retries=3
        )
        
        if not success:
            print(f"[{self.node_id}] ⚠ Falha ao enviar reply_ok para {peer_addr}")
        
    def change_light_state(self, new_state):
        """Muda o estado do semáforo e loga"""
        self.light_state = new_state
        
        # [LAMPORT] Evento local
        current_time = self.clock.tick()
        
        msg = f"Estado mudou para {new_state}"
        print(f"[{self.node_id}] {msg} (L={current_time})")
        
        self.log_to_server(msg, state=new_state, timestamp=current_time)
        
    def log_to_server(self, message, state=None, timestamp=None):
        """
        Envia log para o servidor de logs
        
        [RPC MANUAL] Chamada simples sem esperar resposta
        """
        if state is None:
            state = self.light_state
        if timestamp is None:
            timestamp = self.clock.get_time()
            
        try:
            # [LAMPORT] Evento de envio
            send_time = self.clock.send_time()
            
            # Conecta ao servidor de logs
            log_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            log_socket.settimeout(2.0)
            log_socket.connect(self.logger_addr)
            
            # Monta mensagem RPC
            log_message = {
                "method": "log_event",
                "args": {
                    "node_id": self.node_id,
                    "state": state,
                    "timestamp": timestamp,
                    "message": message
                },
                "clock": send_time
            }
            
            message_str = json.dumps(log_message) + '\n'
            log_socket.sendall(message_str.encode('utf-8'))
            log_socket.close()
            
        except Exception as e:
            # Falha no log não deve parar o sistema
            pass
            
    def run_traffic_cycle(self):
        """
        Ciclo principal do semáforo
        
        Loop infinito que:
        1. Fica vermelho por um tempo
        2. Requisita seção crítica
        3. Entra (fica verde)
        4. Sai (fica vermelho)
        5. Repete
        """
        print(f"\n[{self.node_id}] Iniciando ciclo de operação...\n")
        
        cycle = 1
        
        try:
            while True:
                print(f"\n[{self.node_id}] ========== CICLO {cycle} ==========")
                
                # Período vermelho (não quer entrar na seção crítica)
                red_duration = random.uniform(5, 10)
                print(f"[{self.node_id}] Aguardando {red_duration:.1f}s no vermelho...")
                time.sleep(red_duration)
                
                # Tenta entrar na seção crítica
                self.request_critical_section()
                self.enter_critical_section()
                self.exit_critical_section()
                
                cycle += 1
                
        except KeyboardInterrupt:
            print(f"\n[{self.node_id}] Encerrando...")
            self.comms.stop()


# =============================================================================
# FUNÇÃO PRINCIPAL
# =============================================================================

def parse_peer_address(peer_str):
    """Converte string 'host:port' em tupla (host, port)"""
    host, port = peer_str.split(':')
    return (host, int(port))


def main():
    """Função principal"""
    parser = argparse.ArgumentParser(
        description='Nó de Semáforo Distribuído com Ricart-Agrawala'
    )
    parser.add_argument('--id', type=str, required=True,
                       help='ID único do nó (ex: Node1)')
    parser.add_argument('--host', type=str, required=True,
                       help='Host deste nó (ex: 127.0.0.1)')
    parser.add_argument('--port', type=int, required=True,
                       help='Porta deste nó (ex: 5001)')
    parser.add_argument('--peers', type=str, required=True,
                       help='Lista de peers: host1:port1,host2:port2,...')
    parser.add_argument('--logger', type=str, required=True,
                       help='Endereço do servidor de logs (ex: 127.0.0.1:9000)')
    
    args = parser.parse_args()
    
    # Parseia os peers
    peers = [parse_peer_address(p.strip()) for p in args.peers.split(',')]
    logger_addr = parse_peer_address(args.logger)
    
    # Cria e inicia o nó
    node = TrafficLight(
        node_id=args.id,
        host=args.host,
        port=args.port,
        peers=peers,
        logger_addr=logger_addr
    )
    
    node.start()


if __name__ == '__main__':
    main()