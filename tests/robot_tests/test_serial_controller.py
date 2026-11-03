from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from robot.control.controller import (Runtime, DEFAULTS, PUMP_ID, load_params, move_command,
                                    validate, Cancelled)


class FakeSerial:
    out_waiting = 0
    def __init__(self, fail_after=None):
        self.writes = []
        self.closed = False
        self.fail_after = fail_after
    def write(self, data):
        if self.fail_after is not None and len(self.writes) >= self.fail_after:
            raise OSError("disconnected")
        self.writes.append(data)
        return len(data)
    def close(self):
        self.closed = True


class SerialArmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"ARM_HARDWARE_LOCK_PATH": str(self.root / 'hardware.lock')})
        self.env.start()
        self.addCleanup(self.env.stop)

    def runtime(self, **kwargs):
        rt = Runtime(settings_path=self.root / 'settings.json', **kwargs)
        self.addCleanup(rt.close)
        if not rt.demo:
            rt.serial = FakeSerial()
        return rt

    def test_wire_matches_field_tested_protocol_for_both_branches(self):
        for target, base in (("right",2033),("left",967)):
            rt = self.runtime()
            waits=[]
            rt.wait=waits.append
            rt.execute('sequence',DEFAULTS,target=target)
            poses=[([1500,1223,1722,722,1500,2500],1000),
                   ([base,1500,1722,722,1500,2500],1000),
                   ([base,1033,1622,822,1500,2500],500),
                   ([base,1033,1622,822,1500,500],500),
                   ([1500,1500,1500,1500,1500,1500],1000)]
            expected=[f'#{i:03d}P{p:04d}T{t:04d}!'.encode() for positions,t in poses for i,p in enumerate(positions)]
            self.assertEqual(rt.serial.writes,expected)
            self.assertEqual(waits,[1500,1000,500,500,1000])
            self.assertEqual(rt.pump_position,1500)

    def test_disable_pump_sends_only_joints(self):
        rt=self.runtime(pump_enabled=False);rt.wait=lambda ms:None
        rt.execute('sequence',DEFAULTS)
        self.assertEqual(len(rt.serial.writes),25)
        self.assertTrue(all(not b.startswith(b'#005') for b in rt.serial.writes))
        self.assertFalse(rt.snapshot()['pump_available'])
        with self.assertRaises(ValueError):rt.execute('pump_on',DEFAULTS)

    def test_recovery_uses_same_uart_and_no_neutral_pump_command(self):
        rt=self.runtime();rt.wait=lambda ms:None
        rt.execute('recover',DEFAULTS)
        self.assertEqual(rt.serial.writes[0],b'#005P0500T0500!')
        self.assertEqual(rt.serial.writes[1:],[f'#{i:03d}P1500T1000!'.encode() for i in range(5)])

    def test_stop_rejects_concurrent_action_and_does_not_release_pump(self):
        rt=self.runtime();entered=threading.Event()
        def wait(ms):
            entered.set()
            if rt.cancel.wait(2):raise Cancelled()
        rt.wait=wait
        rt.start('sequence',DEFAULTS)
        self.assertTrue(entered.wait(1))
        with self.assertRaises(ValueError):rt.start('move',DEFAULTS,pose='reset')
        rt.stop();rt.worker.join(2)
        self.assertFalse(rt.busy)
        self.assertEqual(len(rt.serial.writes),11)
        self.assertEqual(rt.serial.writes[-5:],[f'#{i:03d}PDST!'.encode() for i in range(5)])
        self.assertEqual(rt.pump_position,2500)

    def test_write_failure_aborts_without_automatic_reset(self):
        rt=self.runtime();serial=FakeSerial(fail_after=2);rt.serial=serial
        with self.assertRaises(OSError):rt.execute('sequence',DEFAULTS)
        self.assertEqual(len(serial.writes),2)
        self.assertTrue(serial.closed)
        self.assertIsNone(rt.serial)
        self.assertIsNotNone(rt.fault)
        self.assertFalse(rt.busy)

    def test_legacy_angle_settings_are_backed_up_once(self):
        p=self.root/'legacy.json'
        raw={'move_ms':700,'poses':{n:{f's{i}':90 for i in range(1,6)} for n in ('preparation','forward','left','right')}}
        old=json.dumps(raw).encode();p.write_bytes(old)
        self.assertEqual(load_params(p),DEFAULTS)
        backups=list(self.root.glob('legacy.json.legacy-angles-*.bak'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),old)
        self.assertEqual(load_params(p),DEFAULTS)
        self.assertEqual(len(list(self.root.glob('*.bak'))),1)

    def test_invalid_new_settings_are_never_silently_replaced(self):
        p=self.root/'bad.json';p.write_text('{')
        with self.assertRaises(ValueError):load_params(p)
        self.assertEqual(p.read_text(),'{')
        for value in (499,2501,True,float('nan'),'1500'):
            params=copy.deepcopy(DEFAULTS);params['poses']['reset'][0]=value
            with self.assertRaises(ValueError):validate(params)
        self.assertEqual(move_command(3,722,500),b'#003P0722T0500!')

    def test_serial_open_never_sends_or_asserts_feedback(self):
        rt=Runtime(settings_path=self.root/'open.json')
        self.addCleanup(rt.close)
        class SerialModule:
            Serial=lambda *args,**kwargs:FakeSerial()
        with patch.dict('sys.modules',{'serial':SerialModule}):
            rt.connect('/dev/mock-uart')
        self.assertEqual(rt.serial.writes,[])
        self.assertFalse(rt.snapshot()['arm_position_verification'])


if __name__=='__main__':unittest.main()
