"""Behavior tests; dummy keyboard backend avoids needing a desktop session."""
import os
os.environ['PYNPUT_BACKEND'] = 'dummy'
import sys
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
    def test_repeat_and_release(self):
        press, release = Mock(), Mock()
        w = gps.KeyboardWatcher(press, release)
        w.set_trigger('F8')
        k = Key('f8')
        for down in (True, True, True, False):
            w.events.put((k, down))
        w.pump()
        press.assert_called_once()
        release.assert_called_once()

    def test_combo_releases_when_modifier_released_first(self):
        press, release = Mock(), Mock()
        w = gps.KeyboardWatcher(press, release)
        w.set_trigger('CTRL-F9')
        ctrl, key = Key('ctrl_l'), Key('f9')
        for k, down in ((ctrl, True), (key, True), (ctrl, False), (key, False)):
            w.events.put((k, down))
        w.pump()
        press.assert_called_once()
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
        c.args = SimpleNamespace(any_app=False, close_command='auto')
        c.state = c.IDLE
        c._lock = threading.Lock()
        c.cancelled = threading.Event()
        c.recorder = Mock()
        c.sounds = Mock()
        c.keyboard = SimpleNamespace(active=False, down=set())
        c.watcher = SimpleNamespace(_held=set())
        c.target = 42
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

    def test_unknown_foreground_does_not_record(self):
        c = self.coordinator()
        with patch.object(gps, 'wow_is_frontmost', return_value=None):
            c.on_trigger()
        c.recorder.start.assert_not_called()

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
