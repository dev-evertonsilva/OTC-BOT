--[[

Position Exporter Module for OTClient

Este módulo exporta a posição do player para um arquivo JSON
que pode ser lido pelo bot Python para integração.

Coloque este arquivo na pasta mods/ do OTClient
e adicione ao seu otmod ou carregue diretamente.

]]

local exportInterval = 100 -- ms entre exportações
local exportPath = "player_position.json"
local exportEvent = nil
local isEnabled = false

-- Define as constantes de estado do player (valores padrão do Tibia)
local PlayerStates = {
    Poison = 1,
    Burning = 2,
    Electrified = 4,
    Drunk = 8,
    ManaShield = 16,
    Paralyze = 32,
    Haste = 64,
    Swords = 128,
    Drowning = 256,
    Freezing = 512,
    Dazzled = 1024,
    Cursed = 2048,
    Strengthened = 4096,
    ProtectionZone = 8192,
    Trashed = 16384,
    Invisible = 32768
}

-- Função para exportar dados do player para JSON
local function exportPlayerData()
    local player = g_game.getLocalPlayer()
    if not player then
        return
    end

    local pos = player:getPosition()
    -- Valida se a posição é válida
    if not pos or not pos.x or not pos.y or not pos.z then
        return
    end

    local hp = player:getHealth()
    local maxHp = player:getMaxHealth()
    local mana = player:getMana()
    local maxMana = player:getMaxMana()
    local name = player:getName()
    local level = player:getLevel()

    -- Verifica se está atacando algo
    local target = g_game.getAttackingCreature()
    local hasTarget = target ~= nil
    local targetName = ""
    local targetHp = 0

    if target then
        targetName = target:getName()
        targetHp = target:getHealthPercent()
    end

    -- Verifica estados/condições
    local isPoisoned = false
    local isBurning = false
    local isElectrified = false
    local isHasted = false
    local isParalyzed = false
    local isInvisible = false
    local hasManaShield = false

    -- Tenta obter os estados do player
    local success, states = pcall(function() return player:getStates() end)

    if success and states and type(states) == "number" then
        isPoisoned = bit.band(states, PlayerStates.Poison) ~= 0
        isBurning = bit.band(states, PlayerStates.Burning) ~= 0
        isElectrified = bit.band(states, PlayerStates.Electrified) ~= 0
        isHasted = bit.band(states, PlayerStates.Haste) ~= 0
        isParalyzed = bit.band(states, PlayerStates.Paralyze) ~= 0
        isInvisible = bit.band(states, PlayerStates.Invisible) ~= 0
        hasManaShield = bit.band(states, PlayerStates.ManaShield) ~= 0
    end

    -- Monta o JSON
    local data = {
        -- Posição
        x = pos.x,
        y = pos.y,
        z = pos.z,

        -- Stats
        hp = hp or 0,
        maxHp = maxHp or 0,
        mana = mana or 0,
        maxMana = maxMana or 0,
        hpPercent = maxHp and maxHp > 0 and (hp / maxHp * 100) or 0,
        manaPercent = maxMana and maxMana > 0 and (mana / maxMana * 100) or 0,

        -- Info
        name = name or "",
        level = level or 0,

        -- Target
        hasTarget = hasTarget,
        targetName = targetName,
        targetHp = targetHp,

        -- Condições
        isPoisoned = isPoisoned,
        isBurning = isBurning,
        isElectrified = isElectrified,
        isHasted = isHasted,
        isParalyzed = isParalyzed,
        isInvisible = isInvisible,
        hasManaShield = hasManaShield,

        -- Timestamp
        timestamp = os.time()
    }

    -- Converte para JSON e salva com proteção
    local success, jsonStr = pcall(json.encode, data)
    if success and jsonStr then
        g_resources.writeFileContents(exportPath, jsonStr)
    end
end

-- Inicia a exportação periódica
function startExport()
    if isEnabled then
        return
    end

    isEnabled = true

    local function doExport()
        if not isEnabled then
            return
        end

        pcall(exportPlayerData)
        exportEvent = scheduleEvent(doExport, exportInterval)
    end

    doExport()
    print("[PositionExporter] Exportação iniciada: " .. exportPath)
end

-- Para a exportação
function stopExport()
    isEnabled = false
    if exportEvent then
        removeEvent(exportEvent)
        exportEvent = nil
    end
    print("[PositionExporter] Exportação parada")
end

-- Define o intervalo de exportação
function setExportInterval(interval)
    exportInterval = interval
    print("[PositionExporter] Intervalo definido: " .. interval .. "ms")
end

-- Define o caminho do arquivo
function setExportPath(path)
    exportPath = path
    print("[PositionExporter] Caminho definido: " .. path)
end

-- Conecta aos eventos do jogo
function init()
    connect(g_game, {
        onGameStart = startExport,
        onGameEnd = stopExport
    })

    -- Se já estiver logado, inicia exportação
    if g_game.isOnline() then
        startExport()
    end

    print("[PositionExporter] Módulo carregado!")
    print("[PositionExporter] Arquivo salvo em: " .. g_resources.getWriteDir() .. "player_position.json")
end

function terminate()
    stopExport()
    disconnect(g_game, {
        onGameStart = startExport,
        onGameEnd = stopExport
    })
    print("[PositionExporter] Módulo descarregado!")
end

-- API para uso externo
PositionExporter = {
    start = startExport,
    stop = stopExport,
    setInterval = setExportInterval,
    setPath = setExportPath,
    export = exportPlayerData -- exporta uma vez manualmente
}
