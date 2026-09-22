"""Behavior tests; dummy keyboard backend avoids needing a desktop session."""
import os
os.environ['PYNPUT_BACKEND'] = 'dummy'
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helper'))
with patch.dict(sys.modules, {'sounddevice': Mock()}):
    import gamepadspeak_helper as gps

class Key:
    def __init__(self, name):
        self.name = name

class HoldTests(unittest.TestCase):
    def test_mouse_side_buttons_repeat_release_and_rebind(self):
        press, release = Mock(), Mock()
        w = gps.MouseWatcher(press, release)
        w.set_trigger('BUTTON4')
        for name, down in [('left', True), ('x2', True), ('x1', True), ('x1', True), ('x1', False)]:
            w.events.put((SimpleNamespace(name=name), down))
        w.pump()
        press.assert_called_once_with(0)
        release.assert_called_once()
        w.set_trigger('BUTTON5')
        for name, down in [('x1', True), ('x2', True), ('x2', False)]:
            w.events.put((SimpleNamespace(name=name), down))
        w.pump()
        self.assertEqual(press.call_count, 2)
        self.assertEqual(release.call_count, 2)

    def test_mouse_routes_capture_shift_at_press(self):
        press, release = Mock(), Mock()
        w = gps.MouseWatcher(press, release)
        w.routes = {'BUTTON4': 1, 'SHIFT-BUTTON4': 2, 'BUTTON5': 3}
        w.modifiers = lambda: {'SHIFT'}
        w.events.put((SimpleNamespace(name='x1'), True))
        w.pump()
        press.assert_called_once_with(2)
        w.modifiers = lambda: set()
        w.events.put((SimpleNamespace(name='x1'), False))
        w.pump()
        release.assert_called_once()

    def test_addon_sync_install_update_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            wow = Path(tmp) / 'wow'
            self.assertEqual(gps.sync_addon(wow), 'installed')
            self.assertTrue((wow / 'Interface' / 'AddOns' / 'WoWYap' / 'WoWYap.toc').is_file())
            self.assertEqual(gps.sync_addon(wow), 'ok')
            dest = wow / 'Interface' / 'AddOns' / 'WoWYap' / 'WoWYap.toc'
            dest.write_text(dest.read_text(encoding='utf-8') + '\n## X-Test: 1\n', encoding='utf-8')
            self.assertEqual(gps.sync_addon(wow), 'updated')
            cfg = Path(tmp) / 'WoWYap.ini'
            cfg.write_text('# comment\n[wowyap]\nwow_dir = C:\\Games\\WoW\nmodel = base.en\n', encoding='utf-8')
            with patch.object(gps, 'config_path', return_value=cfg):
                loaded = gps.load_user_config()
            self.assertEqual(loaded['wow_dir'], r'C:\Games\WoW')
            self.assertEqual(loaded['model'], 'base.en')
            self.assertEqual(gps.resolve_wow_dir(None, loaded), Path(r'C:\Games\WoW'))

    def test_softer_sounds_have_smooth_edges_and_low_peak(self):
        sounds = gps.Sounds(True)
        for sound in (sounds.start_tone, sounds.stop_tone, sounds.error_tone):
            self.assertLessEqual(float(gps.np.max(gps.np.abs(sound))), 0.056)
            self.assertAlmostEqual(float(sound[0]), 0, places=6)
            self.assertAlmostEqual(float(sound[-1]), 0, places=6)

    def test_repeat_and_release(self):
        press, release = Mock(), Mock()
        w = gps.KeyboardWatcher(press, release)
        w.set_trigger('F8')
        k = Key('f8')
        for down in (True, True, True, False):
            w.events.put((k, down))
        w.pump()
        press.assert_called_once_with(0)
        release.assert_called_once()

    def test_combo_releases_when_modifier_released_first(self):
        press, release = Mock(), Mock()
        w = gps.KeyboardWatcher(press, release)
        w.set_trigger('CTRL-F9')
        ctrl, key = Key('ctrl_l'), Key('f9')
        for k, down in ((ctrl, True), (key, True), (ctrl, False), (key, False)):
            w.events.put((k, down))
        w.pump()
        press.assert_called_once_with(0)
        release.assert_called_once()

    def test_two_physical_modifiers(self):
        w = gps.KeyboardWatcher(Mock(), Mock())
        w.set_trigger('CTRL-F9')
        left, right, key = Key('ctrl_l'), Key('ctrl_r'), Key('f9')
        for k, down in ((left, True), (right, True), (key, True), (left, False)):
            w.events.put((k, down))
        w.pump()
        self.assertTrue(w.active)
        w.events.put((right, False))
        w.pump()
        self.assertFalse(w.active)

    def test_controller_short_taps_not_debounced_away(self):
        press, release = Mock(), Mock()
        w = gps.ControllerWatcher(press, release)
        for _ in range(2):
            w._edge(1, True)
            w._edge(1, False)
        self.assertEqual(press.call_count, 2)
        self.assertEqual(release.call_count, 2)

    def coordinator(self):
        c = gps.Coordinator.__new__(gps.Coordinator)
        c.args = SimpleNamespace(any_app=False, close_command='auto', delivery='chat')
        c.state = c.IDLE
        c._lock = threading.Lock()
        c.cancelled = threading.Event()
        c.recorder = Mock()
        c.sounds = Mock()
        c.keyboard = SimpleNamespace(active=False, down=set())
        c.mouse = SimpleNamespace(active=False)
        c.watcher = SimpleNamespace(_held=set())
        c.target = 42
        c.chat_route = 0
        c.trigger_type = 'keyboard'
        c.transcriber = Mock()
        c.injector = Mock()
        c.hotkey = None
        c.close_key = None
        return c

    def test_start_only_in_wow_and_release_only_once(self):
        c = self.coordinator()
        with patch.object(gps, 'wow_is_frontmost', return_value=False):
            c.on_trigger()
        c.recorder.start.assert_not_called()
        with patch.object(gps, 'wow_is_frontmost', return_value=True), patch.object(gps, 'foreground_identity', return_value=42):
            c.on_trigger()
            c.on_trigger()
        c.recorder.start.assert_called_once()
        self.assertEqual(c.state, c.RECORDING)
        with patch.object(gps.threading, 'Thread'):
            c.on_release()
            c.on_release()
        c.recorder.stop.assert_called_once()

    def test_unknown_foreground_still_records(self):
        # Blank WoW titles used to look like "unknown" and blocked recording.
        c = self.coordinator()
        with patch.object(gps, 'wow_is_frontmost', return_value=None), patch.object(gps, 'foreground_identity', return_value=42):
            c.on_trigger()
        c.recorder.start.assert_called_once()

    def test_focus_loss_discards_transcript(self):
        c = self.coordinator()
        c.state = c.FINALIZING
        c.transcriber.transcribe.return_value = 'hello'
        c.cancelled.set()
        c._finish(None)
        c.injector.deliver.assert_not_called()
        self.assertEqual(c.state, c.IDLE)

    def test_success_sends_and_resets(self):
        c = self.coordinator()
        c.transcriber.transcribe.return_value = 'hello'
        with patch.object(gps, 'wow_is_frontmost', return_value=True), patch.object(gps, 'foreground_identity', return_value=42):
            c._finish(None)
        c.injector.deliver.assert_called_once()
        self.assertEqual(c.state, c.IDLE)
        self.assertIsNone(c.close_command())

    def test_delivery_filters_physical_keydowns_only(self):
        w = gps.KeyboardWatcher(Mock(), Mock())
        w.listener = Mock()
        w.delivery_guard = lambda: True
        w.filter_delivery_keys(0x0100, SimpleNamespace(flags=0))
        w.listener.suppress_event.assert_called_once()
        w.listener.reset_mock()
        # Injected transcript keys and physical releases must pass through.
        w.filter_delivery_keys(0x0100, SimpleNamespace(flags=0x10))
        w.filter_delivery_keys(0x0101, SimpleNamespace(flags=0))
        w.delivery_guard = lambda: False
        w.filter_delivery_keys(0x0100, SimpleNamespace(flags=0))
        w.delivery_guard = None
        w.filter_delivery_keys(0x0100, SimpleNamespace(flags=0))
        w.listener.suppress_event.assert_not_called()

    def test_movement_can_remain_held_during_delivery(self):
        c = self.coordinator()
        c.keyboard.name = gps.KeyboardWatcher.name
        c.keyboard.down.add(Key('w'))
        c.transcriber.transcribe.return_value = 'hello'
        def deliver(*args):
            self.assertTrue(c.keyboard.delivery_guard())
            raise RuntimeError('delivery error')
        c.injector.deliver.side_effect = deliver
        with patch.object(gps, 'wow_is_frontmost', return_value=True), patch.object(gps, 'foreground_identity', return_value=42):
            c._finish(None)
        c.injector.deliver.assert_called_once()
        self.assertIsNone(c.keyboard.delivery_guard)
        self.assertEqual(c.state, c.IDLE)

    def test_failed_transcription_recovers(self):
        c = self.coordinator()
        c.state = c.FINALIZING
        c.transcriber.transcribe.side_effect = RuntimeError('model error')
        c._finish(None)
        self.assertEqual(c.state, c.IDLE)
        c.injector.deliver.assert_not_called()

    def test_failed_mic_can_retry(self):
        c = self.coordinator()
        c.recorder.start.side_effect = RuntimeError('no mic')
        c.begin_recording()
        self.assertEqual(c.state, c.IDLE)

if __name__ == '__main__':
    unittest.main()
