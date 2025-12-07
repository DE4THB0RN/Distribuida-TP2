# Sistema Distribuído de Controle de Semáforos

## Visão Geral

Sistema distribuído implementando:
- **RPC Manual** sobre TCP/IP (sem bibliotecas prontas)
- **Relógios Lógicos de Lamport** para ordenação causal
- **Algoritmo de Ricart-Agrawala** para exclusão mútua distribuída

## Arquitetura

```
┌─────────────────┐
│  Logger Server  │  ← Servidor passivo (apenas logs)
│  (porta 9000)   │
└────────┬────────┘
         │
    ┌────┴────┬─────────┬─────────┐
    │         │         │         │
┌───▼───┐ ┌──▼───┐ ┌───▼───┐ ┌───▼───┐
│ Node1 │ │ Node2│ │ Node3 │ │ Node4 │
│ :5001 │ │ :5002│ │ :5003 │ │ :5004 │
└───────┘ └──────┘ └───────┘ └───────┘
    └─────────┬──────────┬──────────┘
         (Comunicação P2P via RPC Manual)
```

## Como Executar

### Passo 1: Iniciar o Servidor de Logs

Em um terminal:

```bash
python logger_server.py --host 0.0.0.0 --port 9000
```

Você verá:
```
======================================================================
SERVIDOR DE LOGS - PAINEL DE CONTROLE DE SEMÁFOROS
======================================================================
Escutando em 0.0.0.0:9000
Aguardando conexões de nós de semáforo...
======================================================================
```

### Passo 2: Iniciar os Nós de Semáforo

**Abra múltiplos terminais** (um para cada nó).

#### Exemplo com 3 Nós (localhost):

**Terminal 2 - Nó 1:**
```bash
python traffic_node.py --id Node1 --host 127.0.0.1 --port 5001 --peers 127.0.0.1:5002,127.0.0.1:5003 --logger 127.0.0.1:9000
```

**Terminal 3 - Nó 2:**
```bash
python traffic_node.py --id Node2 --host 127.0.0.1 --port 5002 --peers 127.0.0.1:5001,127.0.0.1:5003 --logger 127.0.0.1:9000
```

**Terminal 4 - Nó 3:**
```bash
python traffic_node.py --id Node3 --host 127.0.0.1 --port 5003 --peers 127.0.0.1:5001,127.0.0.1:5002 --logger 127.0.0.1:9000
```

### Passo 3: Observar o Sistema

No terminal do **Logger Server**, você verá os logs coloridos:

```
[14:23:45.123] [Node1] [L=1] RED    | Nó iniciado em estado RED
[14:23:45.234] [Node2] [L=1] RED    | Nó iniciado em estado RED
[14:23:45.345] [Node3] [L=1] RED    | Nó iniciado em estado RED
[14:23:50.456] [Node1] [L=15] YELLOW | Estado mudou para YELLOW
[14:23:51.567] [Node1] [L=16] GREEN  | Estado mudou para GREEN
```

Nos terminais dos **Nós**, você verá as mensagens de sincronização:

```
[Node1] === REQUISITANDO SEÇÃO CRÍTICA (T=15) ===
[Node1] Aguardando 2 respostas...
[Node1] Reply OK de Node2 (1/2)
[Node1] Reply OK de Node3 (2/2)
[Node1] === TODAS AS RESPOSTAS RECEBIDAS ===
[Node1] *** NA SEÇÃO CRÍTICA (VERDE) ***
```

## 🌐 Execução em Máquinas Diferentes

### Topologia de Exemplo (3 máquinas):

```
Máquina A (IP: 192.168.1.10):
    - Logger Server na porta 9000

Máquina B (IP: 192.168.1.11):
    - Node1 na porta 5001

Máquina C (IP: 192.168.1.12):
    - Node2 na porta 5001

Máquina D (IP: 192.168.1.13):
    - Node3 na porta 5001
```

**Máquina A:**
```bash
python logger_server.py --host 0.0.0.0 --port 9000
```

**Máquina B:**
```bash
python traffic_node.py \
    --id Node1 \
    --host 192.168.1.11 \
    --port 5001 \
    --peers 192.168.1.12:5001,192.168.1.13:5001 \
    --logger 192.168.1.10:9000
```

**Máquina C:**
```bash
python traffic_node.py \
    --id Node2 \
    --host 192.168.1.12 \
    --port 5001 \
    --peers 192.168.1.11:5001,192.168.1.13:5001 \
    --logger 192.168.1.10:9000
```

**Máquina D:**
```bash
python traffic_node.py \
    --id Node3 \
    --host 192.168.1.13 \
    --port 5001 \
    --peers 192.168.1.11:5001,192.168.1.12:5001 \
    --logger 192.168.1.10:9000
```

## 🔬 Pontos de Avaliação Acadêmica

### 1. RPC Manual (NodeComms)
- **Localização**: Classe `NodeComms` em `traffic_node.py`
- **Marshaling**: Método `send_rpc()` serializa em JSON
- **Unmarshaling**: Método `_process_rpc_message()` desserializa
- **Dispatch**: Handler despacha para métodos locais

### 2. Relógios de Lamport (LamportClock)
- **Localização**: Classe `LamportClock` em `traffic_node.py`
- **Inicialização**: `L = 0`
- **Evento Local**: `tick()` → `L = L + 1`
- **Envio**: `send_time()` → anexa `L` à mensagem
- **Recebimento**: `receive_time(T)` → `L = max(L, T) + 1`

### 3. Algoritmo de Ricart-Agrawala (TrafficLight)
- **Localização**: Métodos em `TrafficLight`
- **Requisição**: `request_critical_section()` - envia para todos
- **Decisão de Reply**: `handle_request_access()` - compara timestamps
- **Entrada**: `enter_critical_section()` - após N respostas
- **Saída**: `exit_critical_section()` - envia replies diferidas

### 4. Tratamento de Falhas
- **Timeouts**: Todos os `send_rpc()` têm timeout de 5s
- **Exceções**: Try-catch em todas as operações de rede
- **Logs não bloqueantes**: Falha no log não para o nó

## 📊 Saída Esperada

### No Logger Server:
```
[14:30:12.345] [Node1] [L=5]  RED    | Aguardando no vermelho
[14:30:15.678] [Node2] [L=8]  YELLOW | Estado mudou para YELLOW
[14:30:16.789] [Node2] [L=9]  GREEN  | Estado mudou para GREEN
[14:30:20.123] [Node2] [L=12] YELLOW | Estado mudou para YELLOW
[14:30:21.234] [Node2] [L=13] RED    | Estado mudou para RED
[14:30:22.345] [Node3] [L=15] YELLOW | Estado mudou para YELLOW
```

### Nos Nós:
```
[Node1] ========== CICLO 1 ==========
[Node1] Aguardando 7.3s no vermelho...
[Node1] === REQUISITANDO SEÇÃO CRÍTICA (T=15) ===
[Node1] Requisição recebida de Node2 (T=16)
[Node1]   -> WANTED: nossa requisição é mais antiga (15 < 16)
[Node1] Reply OK de Node2 (1/2)
[Node1] Reply OK de Node3 (2/2)
[Node1] === TODAS AS RESPOSTAS RECEBIDAS ===
[Node1] *** NA SEÇÃO CRÍTICA (VERDE) ***
```

## 🧪 Testes Sugeridos

### Teste 1: Exclusão Mútua
- Inicie 4 nós
- Observe que **nunca** dois nós ficam VERDE simultaneamente
- Verifique os timestamps de Lamport no logger

### Teste 2: Ordenação Causal
- Observe que timestamps crescem monotonicamente
- Eventos com `L=5` sempre ocorrem antes de `L=10`

### Teste 3: Falha de Nó
- Inicie 3 nós
- Mate um nó (Ctrl+C)
- Os outros 2 continuam operando (com timeouts)

### Teste 4: Rede Real
- Execute em máquinas diferentes
- Teste latência de rede
- Verifique sincronização mesmo com atrasos

## 🔍 Debug e Troubleshooting

### Problema: "Address already in use"
```bash
# Liberar porta no Linux/Mac
lsof -ti:5001 | xargs kill -9

# No Windows
netstat -ano | findstr :5001
taskkill /PID <PID> /F
```

### Problema: Nós não se comunicam
- Verifique firewall
- Teste conectividade: `telnet <host> <port>`
- Confirme que IPs/portas estão corretos

### Problema: Deadlock aparente
- Verifique se TODOS os peers estão listados corretamente
- Cada nó precisa ter a lista completa de OUTROS nós
- Node1 com peers=[Node2, Node3] ✓
- Node2 com peers=[Node1, Node3] ✓
- Node3 com peers=[Node1, Node2] ✓

