"""Regression tests for native transport and routing (no real OS input)."""
import ctypes
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import test_hold_to_talk as hold

gps = hold.gps


class ReviewTests(unittest.TestCase):
    def api(self):
        api = Mock()
        api.MapVirtualKeyW.side_effect = lambda vk, mode: vk - 0x35
        api.SendInput.side_effect = lambda n, events, size: n
        return api

    def test_windows_batches_decode_through_actual_lua_receiver(self):
        # Exercise the Windows path on every CI OS, with native calls mocked.
        from test_transport import TransportTests
        receiver = TransportTests()
        receiver.setUp()
        api = self.api()
        symbols = {0x43: '0', 0x44: '1', 0x45: 'start', 0x46: 'send'}
        def send(n, events, size):
            self.assertEqual(size, 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
            for i in range(0, n, 2):
                self.assertEqual(events[i].type, 1)
                self.assertEqual(events[i].ki.dwFlags, 8)
                self.assertEqual(events[i+1].ki.dwFlags, 10)
                self.assertEqual(events[i].ki.wScan, events[i+1].ki.wScan)
                receiver.input(symbols[events[i].ki.wScan])
            return n
        api.SendInput.side_effect = send
        sender = gps.WindowsKeySender(api)
        injector = gps.Injector.__new__(gps.Injector)
        injector._windows_sender = sender
        injector.key_hold, injector.packet_delay = 0, .0025
        text = 'Keep moving café'
        with patch.object(gps, 'SYSTEM', 'Windows'), patch.object(gps.time, 'sleep') as sleep:
            injector.deliver_direct(text, route=3)
        length = len(gps.direct_packet(text, 3))
        self.assertEqual(api.SendInput.call_count, length + 2)
        self.assertEqual(api.MapVirtualKeyW.call_count, 4)
        self.assertEqual(sleep.call_count, length)
        self.assertEqual(receiver.lua.eval('sent[1].text'), text)
        self.assertEqual(receiver.lua.eval('sent[1].channel'), 'GUILD')

    def test_partial_native_write_cancels_and_releases_only_reserved_keys(self):
        api = self.api()
        api.SendInput.side_effect = [1, 4]
        sender = gps.WindowsKeySender(api)
        with self.assertRaises(RuntimeError):
            sender.send((0x78, 0x79))
        cleanup = api.SendInput.call_args.args[1]
        self.assertEqual({event.ki.wScan for event in cleanup}, {0x43, 0x44, 0x45, 0x46})
        self.assertTrue(all(event.ki.dwFlags == 10 for event in cleanup))

    def test_shift_snapshot_survives_callback_queue_delay(self):
        press, release = Mock(), Mock()
        watcher = gps.MouseWatcher(press, release)
        watcher.routes = {'BUTTON4': 1, 'SHIFT-BUTTON4': 2}
        watcher.modifiers = lambda: {'SHIFT'}
        watcher._on_click(0, 0, SimpleNamespace(name='x1'), True)
        watcher.modifiers = lambda: set()
        watcher._on_click(0, 0, SimpleNamespace(name='x1'), False)
        watcher.pump()
        press.assert_called_once_with(2)
        release.assert_called_once()

    def test_route_releases_its_own_key_even_if_another_route_is_held(self):
        press, release = Mock(), Mock()
        watcher = gps.KeyboardWatcher(press, release)
        watcher.routes = {'SHIFT-F6': 2, 'F7': 3}
        shift, first, second = hold.Key('shift_l'), hold.Key('f6'), hold.Key('f7')
        for key, down in ((shift, True), (first, True), (second, True), (shift, False)):
            watcher.events.put((key, down))
        watcher.pump()
        release.assert_not_called()
        watcher.events.put((first, False))
        watcher.pump()
        press.assert_called_once_with(2)
        release.assert_called_once()

    def test_unrelated_device_release_does_not_end_recording(self):
        c = hold.HoldTests().coordinator()
        c.state, c.recording_source = c.RECORDING, 'mouse'
        with patch.object(c, 'end_recording') as end:
            c.on_release('keyboard')
            end.assert_not_called()
            c.on_release('mouse')
            end.assert_called_once()

    def test_mouse_routes_keep_primary_keyboard_trigger(self):
        c = hold.HoldTests().coordinator()
        c.args = SimpleNamespace(button=None, raw_button=None, delivery='direct',
                                 open_key='ENTER', close_key='none', close_command='auto')
        c.saved = SimpleNamespace(settings=gps.AddonSettings(trigger='F8', routes=(('BUTTON4', 1),)))
        c.keyboard, c.mouse, c.watcher = Mock(), Mock(), Mock()
        c.apply_settings()
        c.keyboard.set_trigger.assert_called_once_with('F8')
        self.assertEqual(c.mouse.routes, {'BUTTON4': 1})

    def test_switching_to_a_different_wow_window_discards_message(self):
        c = hold.HoldTests().coordinator()
        c.transcriber.transcribe.return_value = 'hello'
        with patch.object(gps, 'wow_is_frontmost', return_value=True), patch.object(gps, 'foreground_identity', return_value=99):
            c._finish(None)
        c.injector.deliver.assert_not_called()

    def test_executable_identity_beats_misleading_window_title(self):
        self.assertFalse(gps.looks_like_wow('World of Warcraft - Google Chrome', 'chrome.exe'))
        self.assertFalse(gps.looks_like_wow('WoWYap', 'python.exe'))
        self.assertTrue(gps.looks_like_wow(None, 'WowClassic.exe'))

    def test_content_hash_detects_same_size_same_time_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, wow = root/'source', root/'wow'
            source.mkdir()
            lua = source/'WoWYap.lua'
            lua.write_text('aaaa')
            gps.sync_addon(wow, source)
            stamp = lua.stat().st_mtime_ns
            lua.write_text('bbbb')
            os.utime(lua, ns=(stamp, stamp))
            self.assertEqual(gps.sync_addon(wow, source), 'updated')
            self.assertEqual((wow/'Interface/AddOns/WoWYap/WoWYap.lua').read_text(), 'bbbb')
            legacy = wow/'Interface/AddOns/GamepadSpeak'
            legacy.mkdir()
            gps.sync_addon(wow, source)
            self.assertFalse(legacy.exists())

    def test_renamed_settings_win_over_newer_legacy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = root/'WTF/Account/test/SavedVariables'
            saved.mkdir(parents=True)
            new, old = saved/'WoWYap.lua', saved/'GamepadSpeak.lua'
            new.write_text('WoWYapDB = {["trigger"] = "F8"}')
            old.write_text('GamepadSpeakDB = {["trigger"] = "F7"}')
            os.utime(old, ns=(new.stat().st_mtime_ns+1000, new.stat().st_mtime_ns+1000))
            reader = gps.SavedVariables(root)
            reader.refresh()
            self.assertEqual(reader.settings.trigger, 'F8')

    def test_ini_percent_paths_and_bom_are_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp)/'WoWYap.ini'
            cfg.write_text('[wowyap]\nwow_dir = D:\\100%Games\\WoW\n', encoding='utf-8-sig')
            with patch.object(gps, 'config_path', return_value=cfg):
                self.assertEqual(gps.load_user_config()['wow_dir'], r'D:\100%Games\WoW')
