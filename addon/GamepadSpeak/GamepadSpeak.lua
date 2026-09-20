-- GamepadSpeak: controller-triggered voice-to-chat for WoW Forever.
--
-- Flow (with the helper running):
--   press trigger  -> helper starts recording, this addon shows "Recording"
--   press again    -> helper stops + transcribes, this addon opens the chat box
--   helper types the text and presses Enter -> message sent, box closed
--
-- The addon is the source of truth for settings. They live in GamepadSpeakDB
-- (WTF/Account/<acct>/SavedVariables/GamepadSpeak.lua); the helper reads that
-- file. WoW only flushes it on /reload or logout, so setup reloads the UI.

local ADDON_NAME = ...

BINDING_HEADER_GAMEPADSPEAK_HEADER = "GamepadSpeak"
BINDING_NAME_GAMEPADSPEAK_OPENCHAT = "Open chat for voice text (used by the helper)"

local DEFAULT_HOTKEY = "CTRL-SHIFT-F12"
local AWAIT_TIMEOUT = 8      -- seconds to wait for the helper's text before closing chat
local RECORD_TIMEOUT = 90    -- seconds before a forgotten recording indicator clears itself

local PREFIX = "|cff69ccf0GamepadSpeak|r: "
local function msg(text) print(PREFIX .. text) end

-- Human names for a DualSense; other pads map the same PAD* codes.
local BUTTON_NAMES = {
	PAD1 = "Cross", PAD2 = "Circle", PAD3 = "Square", PAD4 = "Triangle",
	PAD5 = "Mute", PAD6 = "Button 6",
	PADSOCIAL = "Create", PADFORWARD = "Options", PADSYSTEM = "PS", PADBACK = "Touchpad",
	PADLSHOULDER = "L1", PADRSHOULDER = "R1", PADLTRIGGER = "L2", PADRTRIGGER = "R2",
	PADLSTICK = "L3", PADRSTICK = "R3",
	PADDUP = "D-pad Up", PADDDOWN = "D-pad Down", PADDLEFT = "D-pad Left", PADDRIGHT = "D-pad Right",
	PADPADDLE1 = "Paddle 1", PADPADDLE2 = "Paddle 2", PADPADDLE3 = "Paddle 3", PADPADDLE4 = "Paddle 4",
}

-- Buttons the helper has no SDL mapping for.
local HELPER_BLIND = { PAD6 = true }

local function ButtonLabel(button)
	local name = BUTTON_NAMES[button]
	return name and (button .. " (" .. name .. ")") or button
end

local function IsStickDirection(button)
	return button:match("^PAD[LR]STICK[A-Z]+$") ~= nil
end

------------------------------------------------------------------------
-- State + indicator
------------------------------------------------------------------------
local DB                      -- assigned late, see GetDB / lifecycle below
local seen = {}               -- diagnostics: when the saved table became visible
local observer                -- gamepad button observer frame, created below

-- The saved table must not be created early: if the client applies
-- SavedVariables after ADDON_LOADED and finds a table already there, the
-- file's contents are lost. Create it lazily, as late as possible.
local function GetDB()
	if not DB then
		if type(GamepadSpeakDB) ~= "table" then GamepadSpeakDB = {} end
		DB = GamepadSpeakDB
	end
	return DB
end
local state = "idle"          -- idle | recording | awaiting
local capturing = false
local stateTimer

local indicator = CreateFrame("Frame", "GamepadSpeakIndicator", UIParent)
indicator:SetSize(260, 30)
indicator:SetPoint("TOP", UIParent, "TOP", 0, -90)
indicator:SetFrameStrata("HIGH")
indicator.bg = indicator:CreateTexture(nil, "BACKGROUND")
indicator.bg:SetAllPoints()
indicator.bg:SetColorTexture(0, 0, 0, 0.55)
indicator.text = indicator:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
indicator.text:SetPoint("CENTER")
indicator:Hide()

local function CancelStateTimer()
	if stateTimer then stateTimer:Cancel(); stateTimer = nil end
end

local function SetState(newState, timeout, onTimeout)
	CancelStateTimer()
	state = newState
	if newState == "recording" then
		indicator.text:SetText("|cffff3030\226\151\143|r  Recording")
		indicator:Show()
	elseif newState == "awaiting" then
		indicator.text:SetText("|cffffd100\226\128\166|r  Transcribing")
		indicator:Show()
	else
		indicator:Hide()
	end
	if timeout then
		stateTimer = C_Timer.NewTimer(timeout, function()
			stateTimer = nil
			if state == newState and onTimeout then onTimeout() end
		end)
	end
end

------------------------------------------------------------------------
-- Persistence workaround for the WoW Forever beta (build 69913+): the client
-- writes SavedVariables to disk but never loads them back. Macros live on the
-- server and do survive, so the settings are mirrored into one account macro.
-- The WTF file is still written on /reload, which is what the helper reads.
------------------------------------------------------------------------
local MACRO_NAME = "GPSpeak"
local MACRO_ICON = 134400 -- INV_Misc_QuestionMark
local PERSISTED_KEYS = { "trigger", "chatType", "openOnPress" }
local macroDirty = false

local function Serialize(db)
	local parts = { "#gps v1" }
	for _, key in ipairs(PERSISTED_KEYS) do
		local v = db[key]
		if v ~= nil and v ~= false then
			parts[#parts + 1] = key .. "=" .. tostring(v)
		end
	end
	return "#GamepadSpeak settings. Do not edit or delete.\n" .. table.concat(parts, " ")
end

local function Deserialize(body)
	local line = body and body:match("#gps v1([^\n]*)")
	if not line then return nil end
	local out = {}
	for key, value in line:gmatch("(%w+)=(%S+)") do
		if key == "openOnPress" then
			out[key] = (value == "true") or nil
		else
			out[key] = value
		end
	end
	return out
end

local function SaveToMacro()
	local db = GetDB()
	if InCombatLockdown() then macroDirty = true; return false end
	local body = Serialize(db)
	local index = GetMacroIndexByName(MACRO_NAME)
	if index and index > 0 then
		if GetMacroBody(index) ~= body then EditMacro(index, MACRO_NAME, MACRO_ICON, body) end
	else
		local numAccount = GetNumMacros()
		local maxAccount = MAX_ACCOUNT_MACROS or 120
		if numAccount and numAccount >= maxAccount then
			msg("|cffff5050No free account macro slot;|r settings can't persist on this beta client. Free one macro slot.")
			return false
		end
		CreateMacro(MACRO_NAME, MACRO_ICON, body, nil)
	end
	macroDirty = false
	return true
end

-- Fills in anything the client failed to hand back. Returns true if the macro had data.
local function RestoreFromMacro()
	local index = GetMacroIndexByName(MACRO_NAME)
	if not index or index == 0 then return false end
	local saved = Deserialize(GetMacroBody(index))
	if not saved then return false end
	local db = GetDB()
	for _, key in ipairs(PERSISTED_KEYS) do
		if db[key] == nil and saved[key] ~= nil then db[key] = saved[key] end
	end
	return true
end

------------------------------------------------------------------------
-- Chat handling. Kept minimal on purpose: see the taint note at CloseChat.
------------------------------------------------------------------------
local function Fn(name)
	local f = _G[name]
	if type(f) == "function" then return f end
end

local function GetEditBox()
	local choose = Fn("ChatEdit_ChooseBoxForSend")
	if choose then
		local ok, box = pcall(choose)
		if ok and box then return box end
	end
	if DEFAULT_CHAT_FRAME and DEFAULT_CHAT_FRAME.editBox then return DEFAULT_CHAT_FRAME.editBox end
	return ChatFrame1EditBox
end

local function ActivateChat(editBox)
	local activate = Fn("ChatEdit_ActivateChat")
	if activate then activate(editBox); return end
	local open = Fn("ChatFrame_OpenChat")
	if open then open("", editBox.chatFrame or DEFAULT_CHAT_FRAME); return end
	if editBox.Activate then editBox:Activate(); return end
	editBox:Show()
	editBox:SetFocus()
end

local function RunScript(frame, script)
	local exec = Fn("ExecuteFrameScript")
	if exec then exec(frame, script); return end
	local handler = frame:GetScript(script)
	if handler then handler(frame) end
end

-- Never call ClearFocus/Deactivate on the chat box from addon code: in WoW Forever
-- that runs through the gamepad focus manager into protected calls, taints the
-- gamepad UI and can freeze the client. Mirror an Escape press instead, and only
-- when the box is still focused (the game's own Enter handler normally closes it).
local function CloseChat(editBox)
	editBox = editBox or GetEditBox()
	if not editBox then return end
	if editBox.HasFocus and editBox:HasFocus() then
		pcall(RunScript, editBox, "OnEscapePressed")
	end
end

-- After Enter is pressed (by the helper), just clear our indicator; Blizzard closes the box.
local function OnEnterPressedHook(editBox)
	if state ~= "awaiting" then return end
	SetState("idle")
end

local function HookEditBox(editBox)
	if editBox.gamepadSpeakHooked then return end
	editBox.gamepadSpeakHooked = true
	editBox:HookScript("OnEnterPressed", OnEnterPressedHook)
end

-- Called by the helper's hotkey (Bindings.xml) and by the second trigger press.
function GamepadSpeak_OpenChat()
	local editBox = GetEditBox()
	if not editBox then return end
	HookEditBox(editBox)
	if DB and DB.chatType then
		if editBox.SetChatType then
			editBox:SetChatType(DB.chatType)
		else
			editBox:SetAttribute("chatType", DB.chatType)
		end
		local updateHeader = Fn("ChatEdit_UpdateHeader")
		if updateHeader then updateHeader(editBox) end
	end
	ActivateChat(editBox)
	if not (editBox.HasFocus and editBox:HasFocus()) then
		editBox:SetFocus()
	end
	editBox:SetText("")
	-- On timeout only the indicator is cleared; closing the box from addon code
	-- is not safe in this client (see CloseChat). Circle/B closes it by hand.
	SetState("awaiting", AWAIT_TIMEOUT, function() SetState("idle") end)
end

local CHAT_API_NAMES = {
	"ChatEdit_ActivateChat", "ChatEdit_DeactivateChat", "ChatEdit_ChooseBoxForSend", "ChatEdit_UpdateHeader",
	"ChatEdit_SendText", "ChatEdit_OnEnterPressed", "ChatFrame_OpenChat", "ExecuteFrameScript",
	"IsUsingGamepad", "SetGamePadCursorControl", "GetCurrentKeyBoardFocus",
}
local function DumpApi()
	for _, name in ipairs(CHAT_API_NAMES) do
		msg(name .. ": " .. (Fn(name) and "|cff40ff40yes|r" or "|cffff5050no|r"))
	end
	msg("C_InputInterfaceStyle: " .. tostring(C_InputInterfaceStyle and C_InputInterfaceStyle.GetCurrentStyle and C_InputInterfaceStyle.GetCurrentStyle() or "n/a"))
	local eb = GetEditBox()
	if eb then
		local methods = {}
		for _, m in ipairs({ "Activate", "Deactivate", "SetChatType", "GetChatType", "HasFocus", "Insert", "GetUTF8CursorPosition" }) do
			if eb[m] then methods[#methods + 1] = m end
		end
		msg("Edit box: " .. (eb:GetName() or "unnamed") .. " methods: " .. table.concat(methods, ", "))
		msg("Edit box OnEnterPressed script: " .. tostring(eb:GetScript("OnEnterPressed") ~= nil))
	else
		msg("Edit box: |cffff5050not found|r")
	end
	msg("Observer EnableGamePadButton: " .. tostring(observer and observer.EnableGamePadButton ~= nil))
end

------------------------------------------------------------------------
-- Leaving chat after a send. In gamepad interface style the edit box keeps
-- focus until the Back button (Circle/B) is pressed. Blizzard routes that
-- button through an override binding that clicks a named button, so the same
-- thing can be done with a real keyboard: type "/click <that button>" into
-- the chat box and press Enter. The /click slash command is secure and the
-- handler is Blizzard code, so nothing is tainted. (SecureHandler snippets
-- would be cleaner, but this beta client cannot compile them.)
------------------------------------------------------------------------
local function ComputeCloseCommand()
	local key = GAMEPAD_FACE_RIGHT or "PAD2"
	return "/click InputFunctionBindingButton_" .. key .. " LeftButton 1"
end

------------------------------------------------------------------------
-- Controller observation
------------------------------------------------------------------------
observer = CreateFrame("Frame", "GamepadSpeakObserver", UIParent)
observer:SetSize(1, 1)
observer:SetPoint("CENTER")
observer:EnableKeyboard(false)
observer:Show()

local function ApplyObserverMode()
	-- Propagation can only be changed out of combat; retried on PLAYER_REGEN_ENABLED.
	if InCombatLockdown() then return false end
	if not observer.EnableGamePadButton then
		msg("|cffff5050This client has no EnableGamePadButton on frames; the addon can't observe the controller.|r")
		return false
	end
	observer:EnableGamePadButton(true)
	observer:SetPropagateKeyboardInput(not capturing)
	return true
end

local function OnTriggerPressed()
	if state == "idle" then
		SetState("recording", RECORD_TIMEOUT, function() SetState("idle") end)
	elseif state == "recording" then
		if DB and DB.openOnPress then
			GamepadSpeak_OpenChat()
		else
			SetState("awaiting", AWAIT_TIMEOUT, function() SetState("idle") end)
		end
	end
	-- "awaiting": ignore presses until the text lands or the timeout fires.
end

local function FinishCapture(button)
	capturing = false
	ApplyObserverMode()

	GetDB().trigger = button
	SaveToMacro()
	msg("Trigger set to " .. ButtonLabel(button) .. ".")

	local action = GetBindingAction(button)
	if action and action ~= "" then
		msg("|cffffd100Note:|r that button is also bound to '" .. action .. "' and will still do that. Run /gps setup again with a free button if that bothers you.")
	end
	if HELPER_BLIND[button] then
		msg("|cffff5050Warning:|r the helper cannot see this button. Pick another one with /gps setup.")
	end
	-- Reload flushes SavedVariables so the helper can read the trigger. It must be
	-- called straight from the input event; from a timer the client refuses it.
	msg("Saving and reloading the UI so the helper picks up the new trigger...")
	ReloadUI()
end

observer:SetScript("OnGamePadButtonDown", function(_, button)
	if capturing then
		if IsStickDirection(button) then return end
		FinishCapture(button)
		return
	end
	if DB and DB.trigger and button == DB.trigger then
		OnTriggerPressed()
	end
end)

local function StartCapture()
	if InCombatLockdown() then
		msg("Can't run setup in combat. Try again after the fight.")
		return
	end
	capturing = true
	if not ApplyObserverMode() then
		capturing = false
		return
	end
	SetState("idle")
	msg("Press the controller button you want to use for voice chat. A button with no game action is best (Create, Touchpad, or a D-pad direction you don't use).")
	C_Timer.After(30, function()
		if capturing then
			capturing = false
			ApplyObserverMode()
			msg("Setup timed out. Run /gps setup to try again.")
		end
	end)
end

------------------------------------------------------------------------
-- Hotkey the helper uses to pop the chat box
------------------------------------------------------------------------
local function EnsureHotkey()
	local DB = GetDB()
	local bound = GetBindingKey("GAMEPADSPEAK_OPENCHAT")
	if not bound and not InCombatLockdown() then
		local want = DB.hotkey or DEFAULT_HOTKEY
		local existing = GetBindingAction(want)
		if existing == nil or existing == "" then
			if SetBinding(want, "GAMEPADSPEAK_OPENCHAT") then
				SaveBindings(GetCurrentBindingSet())
				bound = want
			end
		else
			msg("|cffffd100Note:|r " .. want .. " is already bound to '" .. existing .. "'. Bind 'Open chat for voice text' under Key Bindings > AddOns, then run /gps hotkey.")
		end
	end
	DB.hotkey = bound
end

------------------------------------------------------------------------
-- Slash commands
------------------------------------------------------------------------
local CHAT_TYPES = { say = "SAY", yell = "YELL", party = "PARTY", raid = "RAID", guild = "GUILD", officer = "OFFICER", instance = "INSTANCE_CHAT", sticky = nil }

local function ShowStatus()
	local DB = GetDB()
	local index = GetMacroIndexByName(MACRO_NAME)
	msg("Settings macro '" .. MACRO_NAME .. "': " .. ((index and index > 0) and "present" or "|cffff5050missing|r (beta client does not load SavedVariables; the macro is the backup)"))
	msg("Trigger: " .. (DB.trigger and ButtonLabel(DB.trigger) or "|cffff5050not set|r (run /gps setup)"))
	msg("Helper hotkey: " .. (DB.hotkey or "|cffff5050none|r"))
	msg("Channel: " .. (DB.chatType or "last used (sticky)"))
	msg("Close command: " .. ComputeCloseCommand() .. " (PAD2 is bound to '" .. tostring(GetBindingAction("PAD2")) .. "')")
	msg("Open chat on second press: " .. (DB.openOnPress and "on" or "off") .. " (off = helper opens it with Enter)")
	msg("Using gamepad now: " .. tostring(IsUsingGamepad and IsUsingGamepad() or false)
		.. ", active device: " .. tostring(C_GamePad and C_GamePad.GetActiveDeviceID and C_GamePad.GetActiveDeviceID() or "?"))
end

local function SlashHandler(input)
	local DB = GetDB()
	input = (input or ""):gsub("^%s+", ""):gsub("%s+$", "")
	local cmd, rest = input:match("^(%S*)%s*(.-)$")
	cmd = cmd:lower()

	if cmd == "setup" then
		StartCapture()
	elseif cmd == "status" or cmd == "" then
		ShowStatus()
	elseif cmd == "test" then
		local text = rest ~= "" and rest or "GamepadSpeak test message"
		GamepadSpeak_OpenChat()
		local editBox = GetEditBox()
		editBox:Insert(text)
		RunScript(editBox, "OnEnterPressed")
	elseif cmd == "channel" then
		local key = rest:lower()
		if key == "" then
			msg("Usage: /gps channel say|yell|party|raid|guild|officer|instance|sticky")
		elseif key == "sticky" then
			DB.chatType = nil
			SaveToMacro()
			msg("Channel: last used (sticky).")
		elseif CHAT_TYPES[key] then
			DB.chatType = CHAT_TYPES[key]
			SaveToMacro()
			msg("Channel: " .. DB.chatType)
		else
			msg("Unknown channel '" .. rest .. "'.")
		end
	elseif cmd == "open" then
		DB.openOnPress = (rest:lower() == "on") or nil
		SaveToMacro()
		msg("Close command: " .. ComputeCloseCommand() .. " (PAD2 is bound to '" .. tostring(GetBindingAction("PAD2")) .. "')")
	msg("Open chat on second press: " .. (DB.openOnPress and "on" or "off"))
	elseif cmd == "hotkey" then
		DB.hotkey = GetBindingKey("GAMEPADSPEAK_OPENCHAT")
		msg("Helper hotkey: " .. (DB.hotkey or "|cffff5050none|r") .. ". Type /reload so the helper reads it.")
	elseif cmd == "api" then
		DumpApi()
	elseif cmd == "reset" then
		wipe(DB)
		local index = GetMacroIndexByName(MACRO_NAME)
		if index and index > 0 and not InCombatLockdown() then DeleteMacro(index) end
		msg("Settings cleared. Run /gps setup.")
	else
		msg("Commands:")
		msg("  /gps setup   - pick the controller trigger button")
		msg("  /gps status  - show current settings")
		msg("  /gps test [text] - send text through the same path the helper uses")
		msg("  /gps channel <say|party|raid|guild|officer|instance|sticky>")
		msg("  /gps open <on|off> - addon opens chat on the second press (default off; helper uses Enter)")
		msg("  /gps hotkey  - re-read the helper hotkey from your key bindings")
		msg("  /gps api     - show which chat functions this client has (for debugging)")
		msg("  /gps reset")
	end
end

SLASH_GAMEPADSPEAK1 = "/gamepadspeak"
SLASH_GAMEPADSPEAK2 = "/gps"
SlashCmdList.GAMEPADSPEAK = SlashHandler

------------------------------------------------------------------------
-- Lifecycle
------------------------------------------------------------------------
local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("PLAYER_REGEN_ENABLED")
events:RegisterEvent("ADDON_ACTION_FORBIDDEN")
events:RegisterEvent("UPDATE_MACROS")

local function Init()
	local db = GetDB()
	RestoreFromMacro()
	ApplyObserverMode()
	db.closeCommand = ComputeCloseCommand()
	EnsureHotkey()
	local editBox = GetEditBox()
	if editBox then HookEditBox(editBox) end
	if db.trigger then
		msg("Trigger: " .. ButtonLabel(db.trigger) .. ". Start the helper and press it to record.")
	else
		msg("No trigger button yet. Type /gps setup and press a controller button.")
	end
end

events:SetScript("OnEvent", function(self, event, arg1, arg2)
	if event == "ADDON_LOADED" then
		if arg1 == ADDON_NAME then seen.addonLoaded = type(GamepadSpeakDB) == "table" end
	elseif event == "PLAYER_LOGIN" then
		seen.login = type(GamepadSpeakDB) == "table"
	elseif event == "PLAYER_ENTERING_WORLD" then
		if seen.enteringWorld == nil then
			seen.enteringWorld = type(GamepadSpeakDB) == "table"
			Init()
		end
	elseif event == "PLAYER_REGEN_ENABLED" then
		ApplyObserverMode()
		if macroDirty then SaveToMacro() end
	elseif event == "UPDATE_MACROS" then
		-- Macros can arrive from the server after the first login of a session.
		if DB and not DB.trigger and RestoreFromMacro() and DB.trigger then
			msg("Settings restored from macro. Trigger: " .. ButtonLabel(DB.trigger) .. ".")
		end
	elseif event == "ADDON_ACTION_FORBIDDEN" and arg1 == ADDON_NAME then
		if tostring(arg2):find("Reload") then
			msg("The client refused the automatic reload. Type |cffffd100/reload|r to save the trigger for the helper.")
		else
			msg("|cffff5050Blocked call:|r " .. tostring(arg2) .. " (please report this)")
		end
	end
end)
