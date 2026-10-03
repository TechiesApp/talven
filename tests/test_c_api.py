"""Explicit scalar C exports, module composition and C library boundary checks."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest

from talven.__main__ import main
from talven.backend import emit_c
from talven.c_api import emit_c_api
from talven.context import encode
from talven.frontend import CompileError, analyze

ROOT = Path(__file__).resolve().parents[1]

class CApiTests(unittest.TestCase):
    def test_deterministic_exports_hashes_zero_arg_bool_keyword_and_no_main(self):
        source='fn auto(x:i32,flag:bool)->bool{return flag && x>=0;} fn value()->i32{return 42;}'
        analysis=analyze(source)
        result=emit_c_api(analysis,'example',['value','auto'])
        self.assertEqual(result, emit_c_api(analysis,'example',['auto','value']))
        self.assertEqual(['auto','value'], [f['name'] for f in result['exports']])
        self.assertEqual('talven_m7_example_f_auto',result['exports'][0]['symbol'])
        for code in ('header','c'):
            self.assertEqual(hashlib.sha256(result[code].encode()).hexdigest(),result[code+'_hash'])
        self.assertNotIn('int main(void)',result['c'])
        self.assertIn('tv_m7_example_f_auto',result['c'])
        self.assertIn('int32_t talven_m7_example_f_value(void);',result['header'])
        self.assertEqual(result['c'],emit_c_api(analyze('// tv_f_auto 😀\n'+source),'example',['auto','value'])['c'])

    def test_rejects_invalid_modules_exports_boundary_types_and_budgets(self):
        analysis=analyze('struct P{x:i32} fn f(x:i32)->i32{return x;} fn borrowed(p:&P)->i32{return p.x;} fn text()->str{return "x";} fn record()->P{return P{x:0};}')
        for module,exports,code in [('', ['f'],'E1001'),('é',['f'],'E1001'),('9bad',['f'],'E1001'),('a'*65,['f'],'E1001'),('ok',[],'E1001'),('ok',['f','f'],'E1001'),('ok',['missing'],'E1001'),('ok',['borrowed'],'E1001'),('ok',['text'],'E1001'),('ok',['record'],'E1001')]:
            with self.subTest(module=module,exports=exports), self.assertRaises(CompileError) as caught:
                emit_c_api(analysis,module,exports)
            self.assertEqual(code,caught.exception.code)
        result=emit_c_api(analysis,'ok',['f'])
        size=len(encode(result).encode())
        self.assertEqual(result,emit_c_api(analysis,'ok',['f'],max_bytes=size))
        for budget in (size-1,0,16*1024*1024+1,True):
            with self.assertRaises(CompileError) as caught:
                emit_c_api(analysis,'ok',['f'],max_bytes=budget)
            self.assertEqual('E1002',caught.exception.code)
        with self.assertRaises(CompileError):
            emit_c(analysis,freestanding=True,library=True)

    def test_namespaces_are_injective_and_header_guards_keep_case(self):
        one=emit_c_api(analyze('fn c()->i32{return 1;}'),'a_b',['c'])
        two=emit_c_api(analyze('fn b_c()->i32{return 2;}'),'a',['b_c'])
        self.assertNotEqual(one['exports'][0]['symbol'],two['exports'][0]['symbol'])
        lower=emit_c_api(analyze('fn f()->i32{return 1;}'),'math',['f'])
        upper=emit_c_api(analyze('fn f()->i32{return 2;}'),'Math',['f'])
        self.assertNotEqual(lower['header'].splitlines()[1],upper['header'].splitlines()[1])

    def test_console_opt_in_applies_to_unexported_functions(self):
        analysis=analyze('fn f()->i32{return 0;} fn unused()->i32{return print("tv_f_f");}')
        with self.assertRaises(CompileError) as caught:
            emit_c_api(analysis,'demo',['f'])
        self.assertEqual('E0404',caught.exception.code)
        self.assertTrue(emit_c_api(analysis,'demo',['f'],console=True)['console'])

    def test_cli_is_read_only_json_and_reports_source_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'source.tal'
            path.write_text('fn f()->i32{return 0;}')
            data=path.read_bytes()
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(0,main(['emit-c-api',str(path),'--module','demo','--export','f']))
            self.assertEqual('talven.c-api.v1',json.loads(output.getvalue())['schema'])
            self.assertEqual(data,path.read_bytes())
            path.write_text('fn f()->i32{return false;}')
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(1,main(['emit-c-api',str(path),'--module','demo','--export','f']))
            self.assertEqual('E0201',json.loads(output.getvalue())['diagnostics'][0]['code'])

class CApiNativeTests(unittest.TestCase):
    def execute(self, receipts, driver, arguments=(), optimization='-O2', sanitizer=False):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            sources=[]
            for index, receipt in enumerate(receipts):
                module=receipt['module']
                (root/(module+'.h')).write_text(receipt['header'])
                path=root/(str(index)+'.c'); path.write_text(receipt['c']); sources.append(str(path))
            path=root/'driver.c'; path.write_text(driver)
            flags=['cc','-std=c11',optimization,'-fno-lto','-Wall','-Wextra','-Werror','-pedantic-errors']
            if sanitizer: flags+=['-fsanitize=address,undefined','-fno-sanitize-recover=all']
            binary=root/'program'
            subprocess.run([*flags,*sources,str(path),'-o',str(binary)],check=True,capture_output=True,timeout=30)
            return subprocess.run([str(binary),*arguments],capture_output=True,timeout=5)

    def test_two_modules_libc_strtol_and_scalar_boundaries_with_sanitizers(self):
        math=emit_c_api(analyze((ROOT/'examples/c-api-math.tal').read_text()),'math',['adjust','accepts'])
        offset=emit_c_api(analyze((ROOT/'examples/c-api-offset.tal').read_text()),'offset',['adjust'])
        driver='''#include "math.h"
#include "offset.h"
#include <stdlib.h>
#include <errno.h>
#include <limits.h>
int main(int argc,char**argv){
    if(argc!=2)return 2;
    char* end;errno=0;long parsed=strtol(argv[1],&end,10);
    if(errno==ERANGE||*end||end==argv[1]||parsed<INT32_MIN||parsed>INT32_MAX)return 2;
    int32_t value=(int32_t)parsed;
    int32_t bounded=value<-1000?-1000:value>1000?1000:value;
    int32_t expected=bounded*2+1;
    if(talven_m4_math_f_adjust(value)!=expected)return 1;
    if(talven_m4_math_f_accepts(value)!=(value>=-1000&&value<=1000))return 1;
    if(talven_m6_offset_f_adjust(expected)!=expected/2+7)return 1;
    return 0;
}'''
        for optimization in ('-O0','-O2'):
            for value in ('-2147483648','2147483647','-1001','-1000','-1','0','1','1000','1001'):
                with self.subTest(optimization=optimization,value=value):
                    result=self.execute([math,offset],driver,[value],optimization,sanitizer=True)
                    self.assertEqual((0,b'',b''),(result.returncode,result.stdout,result.stderr))
        for value in ('','not-a-number','2147483648','999999999999999999999999999'):
            self.assertEqual(2,self.execute([math,offset],driver,[value]).returncode)

    def test_namespaces_link_case_distinct_headers_and_zero_arg_exports(self):
        receipts=[emit_c_api(analyze('fn f()->i32{return 1;}'),'math',['f']), emit_c_api(analyze('fn f()->i32{return 2;}'),'Math',['f'])]
        driver='#include "math.h"\n#include "Math.h"\nint main(void){return talven_m4_math_f_f()+talven_m4_Math_f_f()==3?0:1;}\n'
        # Host filesystem can be case-insensitive; use one combined driver header
        # while preserving both independent guards and separately named units.
        driver=receipts[0]['header']+receipts[1]['header']+'int main(void){return talven_m4_math_f_f()+talven_m4_Math_f_f()==3?0:1;}\n'
        self.assertEqual(0,self.execute(receipts,driver).returncode)

    def test_checked_arithmetic_still_traps_across_export_boundary(self):
        receipt=emit_c_api(analyze('fn inc(x:i32)->i32{return x+1;}'),'trap',['inc'])
        driver='#include "trap.h"\nint main(void){return talven_m4_trap_f_inc(INT32_MAX);}\n'
        result=self.execute([receipt],driver)
        self.assertEqual(-signal.SIGABRT,result.returncode)

if __name__=='__main__':
    unittest.main()
