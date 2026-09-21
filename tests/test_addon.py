"""Run addon logic against a minimal WoW API stub (requires lupa)."""
import unittest
from pathlib import Path
from lupa import LuaRuntime

class AddonTests(unittest.TestCase):
    def test_settings_capture_persist_and_hold_indicator(self):
        lua = LuaRuntime()
        lua.execute('''
        frames = {}; macros = {}; SlashCmdList = {}; UIParent = {}; reloads = 0
        function print(...) end
        function CreateFrame(kind, name, parent, template)
          local f = {scripts={}}
          setmetatable(f, {__index=function(self, key)
            return function() end
          end})
          function f:SetScript(key, fn) self.scripts[key] = fn end
          function f:CreateTexture() return CreateFrame() end
          function f:CreateFontString() return CreateFrame() end
          function f:SetText(text) self.textValue = text end
          function f:Show() self.visible = true end
          function f:Hide() self.visible = false end
          frames[#frames+1] = f
          if name then _G[name] = f end
          return f
        end
        C_Timer = {After=function() end, NewTimer=function() return {Cancel=function() end} end}
        function InCombatLockdown() return false end
        function GetMacroIndexByName() return macros.body and 1 or 0 end
        function GetMacroBody() return macros.body end
        function GetNumMacros() return 0 end
        function CreateMacro(name, icon, body) macros.body=body end
        function EditMacro(index, name, icon, body) macros.body=body end
        function GetBindingAction() return '' end
        function GetBindingKey() return nil end
        function SetBinding() return true end
        function SaveBindings() end
        function GetCurrentBindingSet() return 1 end
        function ReloadUI() reloads=reloads+1 end
        function IsControlKeyDown() return ctrl or false end
        function IsShiftKeyDown() return false end
        function IsAltKeyDown() return false end
        Settings = {
          RegisterCanvasLayoutCategory=function() return {GetID=function() return 7 end} end,
          RegisterAddOnCategory=function() end,
          OpenToCategory=function(id) opened=id end
        }
        ''')
        lua.execute(Path('addon/GamepadSpeak/GamepadSpeak.lua').read_text())
        lua.execute('''
        frames[#frames].scripts.OnEvent(nil, 'PLAYER_ENTERING_WORLD')
        assert(GamepadSpeakDB.trigger == 'F8')
        SlashCmdList.GAMEPADSPEAK('settings')
        assert(opened == 7)
        GamepadSpeakObserver.scripts.OnKeyDown(nil, 'F8')
        assert(GamepadSpeakIndicator.text.textValue:find('Recording'))
        GamepadSpeakObserver.scripts.OnKeyDown(nil, 'F8')
        assert(GamepadSpeakIndicator.text.textValue:find('Recording'))
        GamepadSpeakObserver.scripts.OnKeyUp(nil, 'F8')
        assert(GamepadSpeakIndicator.text.textValue:find('Transcribing'))
        SlashCmdList.GAMEPADSPEAK('setup')
        ctrl = true
        GamepadSpeakObserver.scripts.OnKeyDown(nil, 'F9')
        assert(GamepadSpeakDB.trigger == 'CTRL-F9')
        assert(GamepadSpeakDB.triggerType == 'keyboard')
        assert(macros.body:find('trigger=CTRL%-F9'))
        assert(reloads == 1)
        SlashCmdList.GAMEPADSPEAK('setup')
        GamepadSpeakObserver.scripts.OnKeyDown(nil, 'ESCAPE')
        assert(reloads == 1)
        ''')

if __name__ == '__main__': unittest.main()
