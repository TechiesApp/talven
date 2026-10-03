"""Native C export bytes, explicit interface bounds and independent C callers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))
from talven.c_api import emit_c_api
from talven.frontend import CompileError, analyze
import test_c_api as acceptance

BINARY=Path(os.environ.get('TALVEN_NATIVE',ROOT/'experiments/native-compiler/target/release/talven-native')).resolve()

class NativeCApiTests(unittest.TestCase):
    def command(self, source, module, exports, *flags):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'source.tal';path.write_text(source)
            command=[str(BINARY),'emit-c-api',str(path),'--module',module]
            for name in exports: command+=['--export',name]
            result=subprocess.run([*command,*map(str,flags)],capture_output=True,timeout=5)
            self.assertEqual(source,path.read_text())
            return result

    def native(self, analysis, module, exports, *, console=False):
        result=self.command(analysis.source,module,exports,*(['--console'] if console else []))
        self.assertEqual((0,b''),(result.returncode,result.stderr),result.stdout)
        return json.loads(result.stdout)

    def test_native_byte_exact_artifacts_and_interface_facts(self):
        cases=[('fn auto(x:i32,b:bool)->bool{return b && x>=0;} fn value()->i32{return 42;}','demo',['value','auto']),
               ('struct P{x:i32} fn make(x:i32)->P{return P{x:x};} fn get(x:i32)->i32{return make(x).x;}','records',['get']),
               ('fn f()->i32{return print("tv_f_f 😀");}','console',['f'])]
        for source,module,exports in cases:
            console=module=='console'
            analysis=analyze(source)
            expected=emit_c_api(analysis,module,exports,console=console)
            result=self.native(analysis,module,exports,console=console)
            for key in expected:
                if key!='compiler_hash': self.assertEqual(expected[key],result[key],key)

    def test_native_runs_independent_module_library_boundary_and_trap_drivers(self):
        with patch.object(acceptance,'emit_c_api',self.native):
            for name in ('test_two_modules_libc_strtol_and_scalar_boundaries_with_sanitizers',
                         'test_namespaces_link_case_distinct_headers_and_zero_arg_exports',
                         'test_checked_arithmetic_still_traps_across_export_boundary'):
                with self.subTest(driver=name):
                    instance=acceptance.CApiNativeTests(methodName=name)
                    getattr(instance,name)()

    def test_budget_exact_output_and_negative_boundaries(self):
        source='fn f()->i32{return 0;}'
        result=self.command(source,'demo',['f'])
        self.assertEqual(0,result.returncode)
        exact=self.command(source,'demo',['f'],'--max-bytes',len(result.stdout))
        self.assertEqual(result.stdout,exact.stdout)
        for budget in (0,-1,len(result.stdout)-1,16*1024*1024+1):
            result=self.command(source,'demo',['f'],'--max-bytes',budget)
            self.assertEqual(1,result.returncode,result.stderr)
            self.assertEqual('E1002',json.loads(result.stdout)['diagnostics'][0]['code'])
            self.assertNotIn('c',json.loads(result.stdout))

    def test_source_export_and_console_rejections_match_reference_diagnostics(self):
        source='struct P{x:i32} fn f(p:&P)->i32{return p.x;} fn scalar()->i32{return 0;}'
        for module,exports in (('bad-name',['scalar']),('a'*65,['scalar']),('ok',['missing']),('ok',['scalar','scalar']),('ok',['f'])):
            result=self.command(source,module,exports)
            self.assertEqual(1,result.returncode)
            with self.assertRaises(CompileError) as error: emit_c_api(analyze(source),module,exports)
            diagnostic=json.loads(result.stdout)['diagnostics'][0]
            self.assertEqual(error.exception.code,diagnostic['code'])
            self.assertEqual(error.exception.message,diagnostic['message'])
        result=self.command('fn f()->i32{return print("x");}','demo',['f'])
        self.assertEqual('E0404',json.loads(result.stdout)['diagnostics'][0]['code'])
        result=self.command('fn f()->i32{return false;}','demo',['f'])
        self.assertEqual('E0201',json.loads(result.stdout)['diagnostics'][0]['code'])

if __name__=='__main__':
    unittest.main(verbosity=2)
