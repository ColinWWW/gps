-- Focus-free helper transport.
-- F11 starts a packet; F9/F10 carry bits; F12 validates and sends
-- from its key binding's hardware-event context.
-- Protocol v2: GP + version + length + route + payload + checksum.
-- No EditBox, movement calls, keyboard suppression, or secure snippets.
WoWYapTransport = {}
local T = WoWYapTransport
local owner = CreateFrame("Frame")
local packet, symbol, bits, started
local db, report, complete
local channels = {SAY=true, YELL=true, PARTY=true, RAID=true, GUILD=true,
                  OFFICER=true, INSTANCE_CHAT=true}
-- route 0 = addon's /gps channel (or SAY); others are explicit destinations.
local destinations = {
    [1] = "SAY", [2] = "GENERAL", [3] = "GUILD", [4] = "PARTY",
    [5] = "RAID", [6] = "YELL", [7] = "OFFICER", [8] = "INSTANCE_CHAT",
}
local function reset()
    packet, symbol, bits, started = nil, 0, 0, nil
end
reset()

local function sendMessage(text, route)
    local channel, target
    if route and route > 0 then
        channel = destinations[route]
    else
        channel = db.chatType or "SAY"
    end
    if channel == "GENERAL" then
        local name = db.generalChannel or "General"
        target = GetChannelName and GetChannelName(name)
        if not target or target <= 0 then
            report("General channel is not joined. Join it or set its name with /gps general <name>.")
            return false
        end
        channel = "CHANNEL"
    elseif not channels[channel] then
        report("Unsupported direct chat channel.")
        return false
    end
    local send = C_ChatInfo and C_ChatInfo.SendChatMessage or SendChatMessage
    if not send then report("This client has no SendChatMessage API."); return false end
    local ok, err
    if channel == "CHANNEL" then
        ok, err = pcall(send, text, channel, nil, target)
    else
        ok, err = pcall(send, text, channel)
        if not ok then
            ok, err = pcall(send, text, channel, nil, nil)
        end
    end
    if not ok then report("Direct send blocked: " .. tostring(err)); return false end
    return true
end

function T.Input(symbolName)
    if not db or db.directProtocol ~= "2" then return end
    if symbolName == "start" then
        reset()
        -- Never deliver over a manually focused chat/settings edit box.
        if GetCurrentKeyBoardFocus and GetCurrentKeyBoardFocus() then
            report("Direct send skipped: a text field has focus. Click the world and speak again.")
            return
        end
        packet, started = {}, GetTime()
        if complete then complete("receiving") end
        return
    end
    if not packet then
        if symbolName == "send" then
            report("Direct send ignored: no packet started. Update helper+addon and /reload.")
        end
        return
    end
    if GetTime() - started > 15 then
        reset(); report("Direct message cancelled (timeout)."); return
    end
    if GetCurrentKeyBoardFocus and GetCurrentKeyBoardFocus() then
        reset(); report("Direct message cancelled (text field focused)."); return
    end
    local digit = tonumber(symbolName)
    if digit == 0 or digit == 1 then
        symbol = symbol * 2 + digit
        bits = bits + 1
        if bits == 8 then
            packet[#packet+1] = symbol
            symbol, bits = 0, 0
            if #packet > 262 then reset(); report("Direct message too long.") end
        end
        return
    end
    if symbolName ~= "send" then reset(); return end
    local data, partial = packet, bits
    reset() -- no retransmission or duplicate send on a repeated final key
    if partial ~= 0 or #data < 8 or data[1] ~= 71 or data[2] ~= 80 or
        data[3] ~= 2 or #data ~= data[4] + 7 then
        if data[1] == 71 and data[2] == 80 and data[3] == 1 then
            report("Direct delivery version mismatch: update addon and helper, then /reload.")
        else
            report("Direct message incomplete; try a shorter phrase or raise helper --packet-delay.")
        end
        if complete then complete("idle") end
        return
    end
    local checksum = 0
    for i=1,#data-2 do checksum = (checksum * 33 + data[i]) % 65521 end
    if checksum ~= data[#data-1] * 256 + data[#data] then
        report("Direct message checksum failed; please speak again.")
        if complete then complete("idle") end
        return
    end
    local chars = {}
    for i=6,#data-2 do
        if data[i] < 32 or data[i] == 127 then
            report("Direct message contains invalid characters.")
            if complete then complete("idle") end
            return
        end
        chars[#chars+1] = string.char(data[i])
    end
    if sendMessage(table.concat(chars), data[5]) then
        report("Sent: " .. table.concat(chars))
        if complete then complete("idle") end
    else
        if complete then complete("idle") end
    end
end

function T.Install(settings, printMessage, onComplete)
    db, report, complete = settings, printMessage, onComplete
    db.directProtocol = nil
    if InCombatLockdown() then return false end
    reset()
    if not SetOverrideBinding or not ClearOverrideBindings then
        report("Direct delivery unavailable: binding API missing."); return false
    end
    ClearOverrideBindings(owner)
    local keys = {F9="D0", F10="D1", F11="START", F12="SEND"}
    local prefixes = {"", "SHIFT-", "CTRL-", "ALT-", "CTRL-SHIFT-",
                      "ALT-SHIFT-", "ALT-CTRL-", "ALT-CTRL-SHIFT-"}
    local trigger = (db.trigger or ""):match("([^%-]+)$")
    if keys[trigger] then
        report("Choose a trigger outside F9-F12 (F11/F12 reserved) for direct delivery.")
        return false
    end
    for key in pairs(keys) do
        for _, prefix in ipairs(prefixes) do
            local action = GetBindingAction(prefix .. key)
            if action and action ~= "" and action ~= "WOWYAP_OPENCHAT" then
                report("Direct delivery needs " .. prefix .. key .. " unbound (currently " .. action .. "). Then /reload.")
                return false
            end
        end
    end
    local ok, err = pcall(function()
        for key, action in pairs(keys) do
            for _, prefix in ipairs(prefixes) do
                SetOverrideBinding(owner, true, prefix .. key, "WOWYAP_" .. action)
            end
        end
    end)
    if not ok then
        ClearOverrideBindings(owner)
        report("Direct delivery bindings failed: " .. tostring(err)); return false
    end
    db.directProtocol = "2"
    report("Direct delivery ready (F9-F12 reserved). Chat stays closed; /reload saves helper settings.")
    return true
end
