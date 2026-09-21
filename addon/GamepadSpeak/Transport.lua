-- Focus-free helper transport. F11 starts a packet, F9/F10 carry bits,
-- F12 validates and sends from its key binding's hardware-event context.
-- No EditBox, movement calls, keyboard suppression, or secure snippets.
GamepadSpeakTransport = {}
local T = GamepadSpeakTransport
local owner = CreateFrame("Frame")
local packet, byte, bits, started
local db, report, complete
local channels = {SAY=true, YELL=true, PARTY=true, RAID=true, GUILD=true,
                  OFFICER=true, INSTANCE_CHAT=true}
local function reset()
    packet, byte, bits, started = nil, 0, 0, nil
end
reset()

function T.Input(symbol)
    if not db or db.directProtocol ~= "1" then return end
    if symbol == "start" then
        reset()
        -- Never deliver over a manually focused chat/settings edit box.
        if GetCurrentKeyBoardFocus and GetCurrentKeyBoardFocus() then return end
        packet, started = {}, GetTime()
        return
    end
    if not packet then return end
    if GetTime() - started > 15 or
        (GetCurrentKeyBoardFocus and GetCurrentKeyBoardFocus()) then
        reset(); report("Direct message cancelled (timeout or text field focused).")
        return
    end
    if symbol == "0" or symbol == "1" then
        byte = byte * 2 + tonumber(symbol)
        bits = bits + 1
        if bits == 8 then
            packet[#packet+1] = byte
            byte, bits = 0, 0
            if #packet > 261 then reset(); report("Direct message too long.") end
        end
        return
    end
    if symbol ~= "send" then reset(); return end
    local data, partial = packet, bits
    reset() -- no retransmission or duplicate send on a repeated final key
    if partial ~= 0 or #data < 7 or data[1] ~= 71 or data[2] ~= 80 or
        data[3] ~= 1 or #data ~= data[4] + 6 then
        report("Direct message incomplete; please speak again."); return
    end
    local checksum = 0
    for i=1,#data-2 do checksum = (checksum * 33 + data[i]) % 65521 end
    if checksum ~= data[#data-1] * 256 + data[#data] then
        report("Direct message checksum failed; please speak again."); return
    end
    local chars = {}
    for i=5,#data-2 do
        if data[i] < 32 or data[i] == 127 then
            report("Direct message contains invalid characters."); return
        end
        chars[#chars+1] = string.char(data[i])
    end
    local channel = db.chatType or "SAY"
    if not channels[channel] then report("Unsupported direct chat channel."); return end
    local send = C_ChatInfo and C_ChatInfo.SendChatMessage or SendChatMessage
    if not send then report("This client has no SendChatMessage API."); return end
    local ok, err = pcall(send, table.concat(chars), channel)
    if not ok then report("Direct send blocked: " .. tostring(err)); return end
    complete()
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
    local keys = {F9="ZERO", F10="ONE", F11="START", F12="SEND"}
    local prefixes = {"", "SHIFT-", "CTRL-", "ALT-", "CTRL-SHIFT-",
                      "ALT-SHIFT-", "ALT-CTRL-", "ALT-CTRL-SHIFT-"}
    local trigger = (db.trigger or ""):match("([^%-]+)$")
    if keys[trigger] then report("Choose a trigger outside F9-F12 for direct delivery."); return false end
    for key in pairs(keys) do
        for _, prefix in ipairs(prefixes) do
            local action = GetBindingAction(prefix .. key)
            if action and action ~= "" and action ~= "GAMEPADSPEAK_OPENCHAT" then
                report("Direct delivery needs " .. prefix .. key .. " unbound (currently " .. action .. "). Then /reload.")
                return false
            end
        end
    end
    local ok, err = pcall(function()
        for key, action in pairs(keys) do
            for _, prefix in ipairs(prefixes) do
                SetOverrideBinding(owner, true, prefix .. key, "GAMEPADSPEAK_" .. action)
            end
        end
    end)
    if not ok then
        ClearOverrideBindings(owner)
        report("Direct delivery bindings failed: " .. tostring(err)); return false
    end
    db.directProtocol = "1"
    report("Direct delivery ready (F9-F12 reserved). Chat stays closed; /reload saves helper settings.")
    return true
end
