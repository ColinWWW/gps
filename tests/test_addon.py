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
        function IsMouseButtonDown(button) return mouseDown == button end
        function IsControlKeyDown() return ctrl or false end
        function IsShiftKeyDown() return shift or false end
        function IsAltKeyDown() return false end
        function wipe(t) for k in pairs(t) do t[k]=nil end end
        function ClearOverrideBindings() bindings={} end
        function SetOverrideBinding(owner, priority, key, action)
          bindings = bindings or {}
          bindings[key]=action
        end
        Settings = {
          RegisterCanvasLayoutCategory=function() return {GetID=function() return 7 end} end,
          RegisterAddOnCategory=function() end,
          OpenToCategory=function(id) opened=id end
        }
        ''')
        lua.execute(Path('addon/WoWYap/Transport.lua').read_text())
        lua.execute(Path('addon/WoWYap/WoWYap.lua').read_text())
        lua.execute('''
        frames[#frames].scripts.OnEvent(nil, 'PLAYER_ENTERING_WORLD')
        assert(WoWYapDB.trigger == 'F8')
        assert(WoWYapDB.directProtocol == '2')
        SlashCmdList.WOWYAP('settings')
        assert(opened == 7)
        WoWYapObserver.scripts.OnKeyDown(nil, 'F8')
        assert(WoWYapIndicator.text.textValue:find('Yapping'))
        WoWYapObserver.scripts.OnKeyDown(nil, 'F8')
        assert(WoWYapIndicator.text.textValue:find('Yapping'))
        WoWYapObserver.scripts.OnKeyUp(nil, 'F8')
        assert(WoWYapIndicator.text.textValue:find('Transcribing'))
        SlashCmdList.WOWYAP('setup')
        ctrl = true
        WoWYapObserver.scripts.OnKeyDown(nil, 'F6')
        assert(WoWYapDB.trigger == 'CTRL-F6')
        assert(WoWYapDB.triggerType == 'keyboard')
        assert(macros.body:find('trigger=CTRL%-F6'))
        assert(reloads == 1)
        SlashCmdList.WOWYAP('setup')
        WoWYapObserver.scripts.OnKeyDown(nil, 'ESCAPE')
        assert(reloads == 1)
        WoWYapSelectMouse4.scripts.OnClick()
        assert(WoWYapDB.trigger == 'BUTTON4')
        assert(WoWYapDB.triggerType == 'mouse')
        assert(reloads == 2)
        mouseDown = 'Button4'
        WoWYapObserver.scripts.OnUpdate()
        assert(WoWYapIndicator.text.textValue:find('Yapping'))
        mouseDown = nil
        WoWYapObserver.scripts.OnUpdate()
        assert(WoWYapIndicator.text.textValue:find('Transcribing'))
        WoWYapSelectMouse5.scripts.OnClick()
        assert(WoWYapDB.trigger == 'BUTTON5')
        assert(reloads == 3)
        WoWYapMouseRoutes.scripts.OnClick()
        assert(WoWYapDB.routes.BUTTON4 == 1)
        assert(WoWYapDB.routes['SHIFT-BUTTON4'] == 2)
        assert(WoWYapDB.routes.BUTTON5 == 3)
        assert(reloads == 4)
        ''')

if __name__ == '__main__': unittest.main()
