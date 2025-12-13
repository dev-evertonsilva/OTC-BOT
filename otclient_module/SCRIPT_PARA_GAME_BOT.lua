--[[
================================================================================
    SCRIPT DE EXPORTAÇÃO DE POSIÇÃO PARA O BOT PYTHON
================================================================================

    COMO USAR:
    1. Crie uma nova config no game_bot do OTClient
    2. Cole este código inteiro no arquivo .lua da config
    3. A posição será exportada automaticamente para o arquivo

    O arquivo será salvo na pasta de dados do OTClient.
    Para descobrir onde fica, olhe a mensagem no console quando logar.
================================================================================
]]

-- Configurações
local EXPORT_INTERVAL = 100 -- ms entre exportações
local EXPORT_FILE = "player_position.json"

-- Variável para controlar o tempo
local lastExport = 0

-- Mostra onde o arquivo será salvo
info("========================================")
info("EXPORTADOR DE POSIÇÃO ATIVO!")
info("Arquivo: " .. g_resources.getWriteDir() .. EXPORT_FILE)
info("Intervalo: " .. EXPORT_INTERVAL .. "ms")
info("========================================")

-- Função para exportar a posição
macro(EXPORT_INTERVAL, "Exportar Posição", function()
    local player = g_game.getLocalPlayer()
    if not player then return end

    local pos = player:getPosition()
    if not pos or not pos.x then return end

    -- Coleta dados
    local hp = player:getHealth() or 0
    local maxHp = player:getMaxHealth() or 1
    local mana = player:getMana() or 0
    local maxMana = player:getMaxMana() or 1
    local name = player:getName() or ""
    local level = player:getLevel() or 0

    -- Target
    local target = g_game.getAttackingCreature()
    local hasTarget = target ~= nil
    local targetName = ""
    local targetHp = 0
    if target then
        targetName = target:getName() or ""
        targetHp = target:getHealthPercent() or 0
    end

    -- Estados (com proteção)
    local isPoisoned = false
    local isBurning = false
    local isHasted = false
    local isParalyzed = false
    local hasManaShield = false

    pcall(function()
        local states = player:getStates()
        if states and type(states) == "number" then
            isPoisoned = bit.band(states, 1) ~= 0
            isBurning = bit.band(states, 2) ~= 0
            isHasted = bit.band(states, 64) ~= 0
            isParalyzed = bit.band(states, 32) ~= 0
            hasManaShield = bit.band(states, 16) ~= 0
        end
    end)

    -- Monta JSON manualmente (mais compatível)
    local jsonStr = string.format([[{
  "x": %d,
  "y": %d,
  "z": %d,
  "hp": %d,
  "maxHp": %d,
  "mana": %d,
  "maxMana": %d,
  "hpPercent": %.2f,
  "manaPercent": %.2f,
  "name": "%s",
  "level": %d,
  "hasTarget": %s,
  "targetName": "%s",
  "targetHp": %d,
  "isPoisoned": %s,
  "isBurning": %s,
  "isHasted": %s,
  "isParalyzed": %s,
  "hasManaShield": %s,
  "timestamp": %d
}]],
        pos.x, pos.y, pos.z,
        hp, maxHp, mana, maxMana,
        maxHp > 0 and (hp / maxHp * 100) or 0,
        maxMana > 0 and (mana / maxMana * 100) or 0,
        name,
        level,
        hasTarget and "true" or "false",
        targetName,
        targetHp,
        isPoisoned and "true" or "false",
        isBurning and "true" or "false",
        isHasted and "true" or "false",
        isParalyzed and "true" or "false",
        hasManaShield and "true" or "false",
        os.time()
    )

    -- Salva o arquivo
    g_resources.writeFileContents(EXPORT_FILE, jsonStr)
end)

--[[
================================================================================
    DEPOIS DE ATIVAR ESTE SCRIPT:

    1. No console do OTClient (Ctrl+T), veja a mensagem com o caminho do arquivo
    2. Copie esse caminho
    3. No bot Python, vá em Settings > Arquivo e cole o caminho
    4. Clique em "Iniciar Monitoramento"
    5. Pronto! A posição vai aparecer no CaveBot
================================================================================
]]
