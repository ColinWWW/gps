"""Cross-language tests: Python's packet must survive the actual Lua decoder."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from lupa import LuaRuntime
import test_hold_to_talk as hold
gps, Key = hold.gps, hold.Key


class TransportTests(TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.execute('''
            now=0; sent={}; notices={}; bindings={}; done=0; channelTarget=nil
            db={trigger="BUTTON4", generalChannel="General"}
            function CreateFrame() return {} end
            function GetTime() return now end
            function GetCurrentKeyBoardFocus() return focused end
            function InCombatLockdown() return combat or false end
            function GetBindingAction(key) return conflict and "ACTION" or "" end
            function ClearOverrideBindings() bindings={} end
            function SetOverrideBinding(owner, priority, key, action) bindings[key]=action end
            function GetChannelName(name) return (name == "General") and 1 or 0 end
            function SendChatMessage(text, channel, _, target)
                if blocked then error("protected call") end
                sent[#sent+1]={text=text, channel=channel, target=target}
            end
            function report(s) notices[#notices+1]=s end
        ''')
        self.lua.execute(Path('addon/GamepadSpeak/Transport.lua').read_text())
        self.lua.execute('GamepadSpeakTransport.Install(db, report, function() done=done+1 end)')
        self.input = self.lua.globals().GamepadSpeakTransport.Input

    def transfer(self, data, final=True):
        self.input('start')
        for byte in data:
            for shift in range(7, -1, -1):
                self.input(str((byte >> shift) & 1))
        if final:
            self.input('send')

    def test_utf8_roundtrip_and_duplicate_final(self):
        self.transfer(gps.direct_packet('hello café 👋'))
        self.input('send')
        self.assertEqual(self.lua.eval('#sent'), 1)
        self.assertEqual(self.lua.eval('sent[1].text'), 'hello café 👋')
        self.assertEqual(self.lua.eval('sent[1].channel'), 'SAY')
        self.assertEqual(self.lua.eval('done'), 1)
        self.assertEqual(self.lua.eval('bindings["CTRL-SHIFT-F9"]'), 'GAMEPADSPEAK_D0')
        self.assertEqual(self.lua.eval('db.directProtocol'), '2')

    def test_route_byte_selects_guild_and_general(self):
        self.transfer(gps.direct_packet('hi guild', route=3))
        self.assertEqual(self.lua.eval('sent[1].channel'), 'GUILD')
        self.transfer(gps.direct_packet('hi general', route=2))
        self.assertEqual(self.lua.eval('sent[2].channel'), 'CHANNEL')
        self.assertEqual(self.lua.eval('sent[2].target'), 1)

    def test_actual_sender_key_sequence_decodes_without_enter_or_wasd(self):
        injector = gps.Injector.__new__(gps.Injector)
        injector.packet_delay = 0
        symbols = {'F9': '0', 'F10': '1', 'F11': 'start', 'F12': 'send'}
        injector.kb = Mock()
        injector.kb.press.side_effect = lambda key: self.input(symbols[key])
        keys = SimpleNamespace(f9='F9', f10='F10', f11='F11', f12='F12')
        with patch.object(gps, 'Key', keys), patch.object(gps, 'DIRECT_BIT_KEYS', ('F9', 'F10')), \
                patch.object(gps.time, 'sleep'):
            injector.deliver_direct('keep moving', route=1)
        self.assertEqual(self.lua.eval('sent[1].text'), 'keep moving')
        self.assertEqual(self.lua.eval('sent[1].channel'), 'SAY')
        self.assertEqual(injector.kb.press.call_count, injector.kb.release.call_count)

    def test_delivery_paces_once_per_byte(self):
        injector = gps.Injector(packet_delay=0.0025)
        injector.kb = Mock()
        sleeps = []
        with patch.object(gps.time, 'sleep', side_effect=lambda s: sleeps.append(s)):
            injector.deliver_direct('hello world')  # 11 payload + 7 header = 18 bytes
        self.assertEqual(len(sleeps), 18)
        self.assertAlmostEqual(sum(sleeps), 0.045, places=3)

    def test_corrupt_checksum_and_partial_messages_not_sent(self):
        data = bytearray(gps.direct_packet('hello'))
        data[5] ^= 1
        self.transfer(data)
        self.transfer(gps.direct_packet('hello')[:-1])
        self.transfer(gps.direct_packet('hello'), final=False)
        self.input('1')
        self.input('send')
        self.assertEqual(self.lua.eval('#sent'), 0)

    def test_focus_timeout_and_protected_send_failure(self):
        self.lua.execute('focused=true')
        self.transfer(gps.direct_packet('hello'))
        self.lua.execute('focused=nil')
        self.transfer(gps.direct_packet('hello'), final=False)
        self.lua.execute('now=16')
        self.input('send')
        self.lua.execute('blocked=true')
        self.transfer(gps.direct_packet('hello'))
        self.assertEqual(self.lua.eval('#sent'), 0)
        self.assertEqual(self.lua.eval('done'), 0)
        self.assertIn('Direct send blocked', self.lua.eval('notices[#notices]'))

    def test_binding_conflict_disables_transport(self):
        self.lua.execute('conflict=true; GamepadSpeakTransport.Install(db, report, function() end)')
        self.assertIsNone(self.lua.eval('db.directProtocol'))
        self.transfer(gps.direct_packet('hello'))
        self.assertEqual(self.lua.eval('#sent'), 0)

    def test_message_limit_and_whitespace(self):
        self.transfer(gps.direct_packet('a' * 255))
        self.assertEqual(len(self.lua.eval('sent[1].text')), 255)
        with self.assertRaises(ValueError):
            gps.direct_packet('a' * 256)
        with self.assertRaises(ValueError):
            gps.direct_packet('  ')

    def test_coordinator_leaves_wasd_and_modifiers_alone(self):
        c = hold.HoldTests().coordinator()
        c.args.delivery = 'direct'
        c.chat_route = 3
        c.saved = SimpleNamespace(settings=gps.AddonSettings(direct_protocol='2'))
        c.keyboard.down = {Key('w'), Key('shift_l')}
        c.keyboard.delivery_guard = None
        c.transcriber.transcribe.return_value = 'hello'
        with patch.object(gps, 'wow_is_frontmost', return_value=True), patch.object(gps, 'foreground_identity', return_value=42):
            c._finish(None)
        self.assertEqual(c.injector.deliver_direct.call_args[0][:2], ('hello', 3))
        c.injector.deliver.assert_not_called()
        self.assertIsNone(c.keyboard.delivery_guard)
        self.assertEqual(len(c.keyboard.down), 2)

    def test_sender_aborts_without_final_send_after_focus_loss(self):
        injector = gps.Injector.__new__(gps.Injector)
        injector.packet_delay = 0
        injector.kb = Mock()
        keys = SimpleNamespace(f9='F9', f10='F10', f11='F11', f12='F12')
        checks = iter([True, True, False])
        with patch.object(gps, 'Key', keys), patch.object(gps, 'DIRECT_BIT_KEYS', ('F9', 'F10')), \
                patch.object(gps.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                injector.deliver_direct('hello', allowed=lambda: next(checks))
        self.assertNotIn(('F12',), [c.args for c in injector.kb.press.call_args_list])
        self.assertEqual(injector.kb.press.call_count, injector.kb.release.call_count)
