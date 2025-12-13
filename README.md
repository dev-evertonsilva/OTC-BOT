# OTC Bot - Python Edition

Bot para OTClient escrito em Python com PyQt6, inspirado no módulo Lua `game_bot`.

## 📋 Requisitos

- Python 3.9+
- Windows/Linux/macOS

## 🚀 Instalação

```bash
# Instalar dependências
pip install -r requirements.txt

# Executar o bot
python bot.py
```

## 🎮 Funcionalidades

### 🩹 Healing
- **Spell Healing**: Configure até 4 slots de spell com hotkey e threshold de HP
- **Potion Healing**: Configure até 4 slots de potion
- **Emergency Healing**: Slots de emergência para HP crítico
- Condições: HP Below, HP Above, Mana Below, Mana Above

### 👥 Party Heal
- Lista de amigos para curar
- Slots de friend healing com threshold individual
- Party Heal AOE quando múltiplos amigos precisam de cura

### 🔧 Tools
- **Auto Haste**: Mantém haste ativo automaticamente
- **Mana Training**: Usa spell de treino quando mana está alta
- **Anti-Paralyze**: Remove paralyze automaticamente
- **Auto Eat**: Come food periodicamente
- **Auto Attack**: Ataque automático em targets

### ⚡ Macros
- Crie macros customizadas com:
  - Nome e hotkey
  - Intervalo de execução (ms)
  - Condições (HP/Mana/Target)
- Execução automática baseada em condições

### 🗺️ CaveBot (Waypoints)

Sistema completo de CaveBot com waypoints para automação de caça.

#### Tipos de Waypoint:
| Tipo | Descrição |
|------|-----------|
| WALK | Andar até a posição |
| ROPE | Usar rope na posição |
| SHOVEL | Usar shovel na posição |
| LADDER | Subir escada |
| STAND | Ficar parado (delay) |
| ACTION | Executar uma hotkey |
| LABEL | Marcador para loops |

#### Como usar:

1. **Modo Gravação**:
   - Clique em "⏺ Gravar (Ctrl+W)"
   - Ande pelo jogo
   - Pressione `Ctrl+W` para gravar cada posição
   - Clique novamente para parar gravação

2. **Adicionar Manual**:
   - Digite as coordenadas X, Y, Z
   - Selecione o tipo de waypoint
   - Clique em "+ Adicionar"

3. **Executar**:
   - Clique em "▶ Ativar" para iniciar o CaveBot
   - Use "⏸ Pausar" para pausar temporariamente

4. **Salvar/Carregar**:
   - Salve seus waypoints em arquivo JSON
   - Carregue waypoints salvos anteriormente

### 📝 Log
- Visualize mensagens do bot em tempo real
- Status do jogador (HP, Mana, Target)
- Estatísticas (heals usados, tempo ativo)

### ⚙️ Settings
- Intervalo de verificação do bot
- Perfis de configuração (salvar/carregar)
- Hotkeys globais
- **Simulação de HP/Mana** para testes

## 🔗 Integração com OTClient

### Método 1: Arquivo JSON (Recomendado)

O bot pode ler a posição do player de um arquivo JSON exportado pelo OTClient.

1. Copie a pasta `otclient_module` para a pasta `mods` do seu OTClient
2. O módulo exportará automaticamente a posição para `player_position.json`
3. No bot, vá em Settings > Leitura de Posição
4. Selecione "Arquivo JSON" e escolha o arquivo
5. Clique em "▶ Iniciar Monitoramento"

**Formato do arquivo JSON:**
```json
{
  "x": 32000,
  "y": 32000,
  "z": 7,
  "hp": 500,
  "maxHp": 1000,
  "mana": 300,
  "maxMana": 500,
  "hpPercent": 50,
  "manaPercent": 60,
  "hasTarget": true,
  "targetName": "Rat",
  "isPoisoned": false,
  "isHasted": true
}
```

### Método 2: HTTP API

Configure um servidor HTTP no OTClient para comunicação em tempo real.

1. URL padrão: `http://localhost:8080/position`
2. O bot fará requisições GET para obter a posição
3. Selecione "HTTP API" nas configurações

### Método 3: Manual

Use os sliders em Settings para simular HP/Mana durante testes.

## 📁 Estrutura de Arquivos

```
OTC Bot/
├── bot.py                 # Código principal do bot
├── requirements.txt       # Dependências Python
├── README.md              # Este arquivo
├── bot_storage/           # Pasta de perfis salvos
│   └── default.json       # Perfil padrão
└── otclient_module/       # Módulo para OTClient
    ├── position_exporter.lua
    └── position_exporter.otmod
```

## ⌨️ Hotkeys Padrão

| Hotkey | Função |
|--------|--------|
| Ctrl+W | Gravar posição (modo gravação) |
| F8 | Iniciar/Parar bot (configurável) |
| F9 | Pausar bot (configurável) |

## 🛠️ Desenvolvimento

### Arquitetura

O bot foi desenvolvido seguindo a arquitetura do módulo Lua do OTClient:

- **BotExecutor**: Executor principal com sistema de macros, hotkeys e callbacks
- **CallbackManager**: Sistema de eventos (onHpChange, onManaChange, etc.)
- **Scheduler**: Agendamento de tarefas futuras
- **BotStorage**: Persistência de configurações em JSON
- **CaveBot**: Sistema de waypoints
- **PositionReader**: Leitura de posição via arquivo/HTTP

### Adicionando novas funcionalidades

```python
# Exemplo: Adicionar uma macro
def minha_funcao(macro):
    if executor.player.hp_percent < 50:
        executor.press_key("F1")
        return True
    return False

executor.add_macro("Minha Macro", minha_funcao, timeout=1000)

# Exemplo: Registrar callback
def on_hp_change(hp, maxHp, oldHp, oldMaxHp):
    print(f"HP mudou: {hp}/{maxHp}")

executor.callbacks.register("onHpChange", on_hp_change)
```

## ⚠️ Aviso

Este bot é apenas para fins educacionais. Use por sua conta e risco.
O uso de bots pode violar os termos de serviço do jogo.

## 📄 Licença

MIT License - Sinta-se livre para modificar e distribuir.
