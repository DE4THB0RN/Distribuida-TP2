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
    def __init__(self):
        self.time = 0
        self.lock = threading.Lock()
        
    def tick(self):
        with self.lock:
            self.time += 1
            return self.time
            
    def send_time(self):
        return self.tick()
        
    def receive_time(self, received_time):
        with self.lock:
            self.time = max(self.time, received_time) + 1
            return self.time
            
    def get_time(self):
        with self.lock:
            return self.time


# =============================================================================
# RPC
# =============================================================================

class NodeComms:
    def __init__(self, host, port, message_handler):
        self.host = host
        self.port = port
        self.message_handler = message_handler  
        self.server_socket = None
        self.running = False
        
    def start_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True
        
        # Thread para aceitar conexões
        accept_thread = threading.Thread(target=self._accept_connections, daemon=True)
        accept_thread.start()
        
    def _accept_connections(self):

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
        buffer = ""
        
        try:
            while self.running:
                data = client_socket.recv(4096)
                if not data:
                    break
                    
                buffer += data.decode('utf-8')

                while '\n' in buffer:
                    message, buffer = buffer.split('\n', 1)
                    if message.strip():
                        self._process_rpc_message(message.strip())
                        
        except Exception as e:
            pass  
        finally:
            client_socket.close()
            
    def _process_rpc_message(self, message):
        try:
            msg_obj = json.loads(message)
            method = msg_obj.get('method', '')
            args = msg_obj.get('args', {})
            clock = msg_obj.get('clock', 0)
            
            self.message_handler(method, args, clock)
            
        except Exception as e:
            print(f"[COMMS] Erro ao processar mensagem RPC: {e}")
            
    def send_rpc(self, peer_address, method, args, clock_time, timeout=3.0, max_retries=3):
        for attempt in range(max_retries):
            try:
                rpc_message = {
                    "method": method,
                    "args": args,
                    "clock": clock_time
                }
                
                message_str = json.dumps(rpc_message) + '\n'
                
                client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client_socket.settimeout(timeout)
                
                client_socket.connect(peer_address)
                client_socket.sendall(message_str.encode('utf-8'))
                client_socket.close()
                
                return True
                
            except (socket.timeout, ConnectionRefusedError, OSError) as e:
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                else:
                    return False
            except Exception as e:
                return False
        
        return False
    
    def check_peer_available(self, peer_address, timeout=1.0):
        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(timeout)
            test_socket.connect(peer_address)
            test_socket.close()
            return True
        except:
            return False
            
    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()


# =============================================================================
# RICART-AGRAWALA
# =============================================================================

class TrafficLight:

    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    
    RELEASED = "RELEASED"
    WANTED = "WANTED"
    HELD = "HELD"
    
    def __init__(self, node_id, host, port, peers, logger_addr):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.peers = peers 
        self.logger_addr = logger_addr 
        
        self.clock = LamportClock()
        
        self.light_state = self.RED
        
        self.mutex_state = self.RELEASED
        self.request_timestamp = 0 
        self.replies_received = set() 
        self.deferred_replies = [] 
        
        self.state_lock = threading.Lock()
        
        self.comms = NodeComms(host, port, self.handle_rpc_message)
        
    def start(self):
        print(f"[{self.node_id}] Iniciando em {self.host}:{self.port}")
        print(f"[{self.node_id}] Peers: {self.peers}")
        
        self.comms.start_server()
        
        self.log_to_server("Nó iniciado em estado RED")
        
        self.wait_for_peers()

        self.run_traffic_cycle()
    
    def wait_for_peers(self):
        print(f"\n[{self.node_id}] Aguardando todos os peers ficarem online...")
        
        max_wait = 60 
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            all_available = True
            
            for peer in self.peers:
                if not self.comms.check_peer_available(peer, timeout=0.5):
                    all_available = False
                    print(f"[{self.node_id}]   Aguardando peer {peer}...")
                    break
            
            if all_available:
                print(f"[{self.node_id}] Todos os peers estão online!")
                time.sleep(2)
                return
            
            time.sleep(1)
        
        print(f"[{self.node_id}] Timeout aguardando peers. Continuando mesmo assim...")
        
    def handle_rpc_message(self, method, args, received_clock):
        self.clock.receive_time(received_clock)
        
        if method == "request_access":
            self.handle_request_access(args, received_clock)
        elif method == "reply_ok":
            self.handle_reply_ok(args)
        else:
            print(f"[{self.node_id}] Método desconhecido: {method}")
            
    def handle_request_access(self, args, request_clock):
        requester_id = args.get('node_id')
        requester_addr = tuple(args.get('address'))
        
        print(f"[{self.node_id}] Requisição recebida de {requester_id} "
              f"(T={request_clock})")
        
        with self.state_lock:
            should_reply = False
            
            if self.mutex_state == self.RELEASED:
                should_reply = True
                print(f"[{self.node_id}]   -> RELEASED: enviando OK imediato")
                
            elif self.mutex_state == self.HELD:
                self.deferred_replies.append((requester_id, requester_addr))
                print(f"[{self.node_id}]   -> HELD: adicionando à fila")
                
            elif self.mutex_state == self.WANTED:
                if request_clock < self.request_timestamp:

                    should_reply = True
                    print(f"[{self.node_id}]   -> WANTED: requisição dele é "
                          f"mais antiga ({request_clock} < {self.request_timestamp})")
                elif request_clock > self.request_timestamp:

                    self.deferred_replies.append((requester_id, requester_addr))
                    print(f"[{self.node_id}]   -> WANTED: nossa requisição é "
                          f"mais antiga ({self.request_timestamp} < {request_clock})")
                else:

                    if requester_id < self.node_id:
                        should_reply = True
                        print(f"[{self.node_id}]   -> WANTED: desempate por ID")
                    else:
                        self.deferred_replies.append((requester_id, requester_addr))
                        print(f"[{self.node_id}]   -> WANTED: desempate por ID (nossa prioridade)")
        

        if should_reply:
            self.send_reply_ok(requester_addr)
            
    def handle_reply_ok(self, args):

        replier_id = args.get('node_id')
        
        with self.state_lock:
            self.replies_received.add(replier_id)
            print(f"[{self.node_id}] Reply OK de {replier_id} "
                  f"({len(self.replies_received)}/{len(self.peers)})")
            
    def request_critical_section(self):

        with self.state_lock:
            self.mutex_state = self.WANTED
            self.replies_received = set() 

            self.request_timestamp = self.clock.tick()
            
        print(f"\n[{self.node_id}] === REQUISITANDO SEÇÃO CRÍTICA "
              f"(T={self.request_timestamp}) ===")
        
        successful_sends = 0
        for peer in self.peers:

            send_time = self.clock.send_time()
            
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
                print(f"[{self.node_id}] Falha ao enviar para {peer}")
        
        print(f"[{self.node_id}] Requisições enviadas: {successful_sends}/{len(self.peers)}")
        print(f"[{self.node_id}] Aguardando {len(self.peers)} respostas...")
        
        max_wait = 30 
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
            print(f"[{self.node_id}] Timeout: recebidas {received}/{len(self.peers)} respostas")
            print(f"[{self.node_id}] Continuando mesmo assim...")
        
    def enter_critical_section(self):
        with self.state_lock:
            self.mutex_state = self.HELD
            
        self.change_light_state(self.YELLOW)
        time.sleep(1)
        self.change_light_state(self.GREEN)
        
        print(f"[{self.node_id}] *** NA SEÇÃO CRÍTICA (VERDE) ***")
        
        green_duration = random.uniform(3, 6)
        time.sleep(green_duration)
        
    def exit_critical_section(self):
        self.change_light_state(self.YELLOW)
        time.sleep(1)
        self.change_light_state(self.RED)
        
        with self.state_lock:
            self.mutex_state = self.RELEASED
            deferred = self.deferred_replies.copy()
            self.deferred_replies = []
            
        print(f"[{self.node_id}] Saiu da seção crítica. "
              f"Enviando {len(deferred)} respostas diferidas.")
        
        for node_id, addr in deferred:
            self.send_reply_ok(addr)
            
    def send_reply_ok(self, peer_addr):

        send_time = self.clock.send_time()
        
        success = self.comms.send_rpc(
            peer_addr,
            method="reply_ok",
            args={"node_id": self.node_id},
            clock_time=send_time,
            max_retries=3
        )
        
        if not success:
            print(f"[{self.node_id}] Falha ao enviar reply_ok para {peer_addr}")
        
    def change_light_state(self, new_state):
        self.light_state = new_state
        
        current_time = self.clock.tick()
        
        msg = f"Estado mudou para {new_state}"
        print(f"[{self.node_id}] {msg} (L={current_time})")
        
        self.log_to_server(msg, state=new_state, timestamp=current_time)
        
    def log_to_server(self, message, state=None, timestamp=None):

        if state is None:
            state = self.light_state
        if timestamp is None:
            timestamp = self.clock.get_time()
            
        try:
            send_time = self.clock.send_time()
            
            log_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            log_socket.settimeout(2.0)
            log_socket.connect(self.logger_addr)

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
            pass
            
    def run_traffic_cycle(self):
        print(f"\n[{self.node_id}] Iniciando ciclo de operação...\n")
        
        cycle = 1
        
        try:
            while True:
                print(f"\n[{self.node_id}] ========== CICLO {cycle} ==========")
                
                red_duration = random.uniform(5, 10)
                print(f"[{self.node_id}] Aguardando {red_duration:.1f}s no vermelho...")
                time.sleep(red_duration)
                
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
    host, port = peer_str.split(':')
    return (host, int(port))


def main():
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
    
    peers = [parse_peer_address(p.strip()) for p in args.peers.split(',')]
    logger_addr = parse_peer_address(args.logger)
    
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
