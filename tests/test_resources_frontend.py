"""Focused source provenance tests independent of runtime bookkeeping."""
import unittest

from talven.backend import emit_c
from talven.context import encode, source_hash
from talven.frontend import CompileError, analyze
from talven.formatter import format_source, token_identity
from talven.frontend import lex
from talven.resources import analyze_resources, resource_context, runtime_identity, runtime_sources


def region(body, granted="release(block);", failure=""):
    return ("fn main() -> i32 { region storage(32) { " + body +
            "match (attempt) { Allocation::Granted(block) { " + granted +
            " } Allocation::InvalidRequest { " + failure +
            " } Allocation::Exhausted { " + failure + " } } } return 0; }")


class ResourceFrontendTests(unittest.TestCase):
    def reject(self, source, code):
        with self.assertRaises(CompileError) as caught:
            analyze_resources(source)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_owner_moves_rewraps_and_checked_delegation_preserve_origin(self):
        source = ("fn finish(block: Block) -> i32 { let moved = block; "
                  "let again = Allocation::Granted(moved); match (again) { "
                  "Allocation::Granted(owner) { release(owner); } "
                  "Allocation::InvalidRequest {} Allocation::Exhausted {} } return 0; } " +
                  region("let attempt = reserve(storage, 16, 8);", "finish(block);"))
        analysis = analyze_resources(source)
        facts = resource_context(analysis)
        self.assertEqual(facts["functions"][0]["parameters"][0]["effect"], "consume-and-release")
        self.assertEqual(facts["origins"][1]["capacity"], 32)

    def test_payload_scope_and_early_return_are_linear(self):
        self.reject(region("let attempt = reserve(storage, 1, 1);", ""), "E0321")
        self.reject(region("let attempt = reserve(storage, 1, 1);", "return 1;"), "E0321")
        self.reject("fn f(block: Block) -> i32 { return 0; } fn main() -> i32 { return 0; }", "E0321")
        analyze_resources(region("let attempt = reserve(storage, 1, 1);", "release(block); return 1;"))

    def test_all_returning_match_arms_validate_before_region_exit(self):
        analyze_resources("fn main()->i32{region r(1){let a=reserve(r,1,1);match(a){"
                          "Allocation::Granted(b){return release(b);}"
                          "Allocation::InvalidRequest{return 6;}Allocation::Exhausted{return 7;}}}}")

    def test_pending_moves_do_not_discharge_obligation(self):
        self.reject("fn main()->i32{region r(1){let a=reserve(r,1,1);let b=a;}return 0;}", "E0321")
        self.reject("fn main()->i32{region r(1){let a=reserve(r,1,1);let b=reserve(r,1,1);}return 0;}", "E0321")
        self.reject("fn main()->i32{region r(1){reserve(r,1,1);}return 0;}", "E0321")

    def test_optional_and_continuing_branches_keep_obligations(self):
        self.reject("fn f(block:Block,yes:bool)->i32{let x=yes&&(release(block)==0);return 0;}"
                    "fn main()->i32{return 0;}", "E0321")
        self.reject("fn f(block:Block,yes:bool)->i32{if(yes){release(block);}return 0;}"
                    "fn main()->i32{return 0;}", "E0321")
        analyze_resources("fn f(block:Block,yes:bool)->i32{if(yes){release(block);return 1;}"
                          "else{release(block);}return 0;}fn main()->i32{return 0;}")

    def test_opaque_owners_and_reservations_cannot_escape_or_be_forged(self):
        for source in ("struct R { child: Block }", "struct R { child: Allocation }",
                       "outcome R { Child(Block) }", "outcome R { Child(Allocation) }",
                       "fn f(block:Block)->Block{return block;}",
                       "fn f(attempt:Allocation)->i32{return 0;}",
                       "fn f()->Allocation{return Allocation::Exhausted;}",
                       "fn f()->i32{let forged=Block{};return 0;}",
                       "fn f()->i32{let forged=Allocation::InvalidRequest;return 0;}"):
            with self.subTest(source=source):
                self.reject(source + "fn main()->i32{return 0;}", "E0320")
        self.reject(region("let attempt=reserve(storage,1,1);", "let x=block.length;release(block);"), "E0320")

    def test_existing_borrow_and_move_errors_remain(self):
        self.reject(region("let attempt=reserve(storage,1,1);", "release(block);release(block);"), "E0301")
        self.reject(region("let attempt=reserve(storage,1,1);", "let result=write_byte(&mut block,0,1);"), "E0303")
        self.reject("fn f(block:&Block)->i32{return release(block);}fn main()->i32{return 0;}", "E0304")
        self.reject("fn f(a:&Block,b:Block)->i32{return release(b);} " +
                    region("let attempt=reserve(storage,1,1);", "f(&block,block);"), "E0302")

    def test_capacity_and_region_count_bounds(self):
        for value in ("0", "4097", "999999999999999999999999999999999"):
            self.reject(f"fn main()->i32{{region storage({value}){{}}return 0;}}", "E0320")
        for value in ("1", "4096", "000000001"):
            analyze_resources(f"fn main()->i32{{region storage({value}){{}}return 0;}}")
        analyze_resources("fn main()->i32{" + "region storage(1){}" * 8 + "return 0;}")
        self.reject("fn main()->i32{" + "region storage(1){}" * 9 + "return 0;}", "E0320")

    def test_long_leading_zero_capacity_remains_bounded_and_emittable(self):
        source = "fn main()->i32{region storage(" + "0" * 5000 + "4096){}return 0;}"
        analysis = analyze_resources(source)
        self.assertEqual(resource_context(analysis)["origins"][0]["capacity"], 4096)
        self.assertIn("tv_storage_storage[4096];", emit_c(analysis))
        self.assertEqual(token_identity(lex(source)), token_identity(lex(format_source(source, resources=True))))

    def test_reserved_declarations_do_not_change_other_profiles(self):
        for name in ("Block", "Allocation", "ByteRead", "ByteWrite"):
            source = f"struct {name}{{value:i32}}fn main()->i32{{return 0;}}"
            analyze(source)
            self.assertIn(f"struct tv_s_{name}", emit_c(analyze(source)))
            self.reject(source, "E0102")
        source = "struct Region{value:i32}fn main()->i32{let region=Region{value:1};return region.value;}"
        analyze(source)
        analyze_resources(source.replace("let region=", "let item=").replace("return region.value", "return item.value"))

    def test_formatter_preserves_tokens_comments_and_syntax_only_mode(self):
        source = region("let attempt=reserve(storage,1,1);", "// release intentionally missing\n")
        formatted = format_source(source, resources=True)
        self.assertEqual(token_identity(lex(source, include_comments=True)), token_identity(lex(formatted, include_comments=True)))
        self.assertEqual(formatted, format_source(formatted, resources=True))
        self.reject(formatted, "E0321")

    def test_exact_runtime_emission_and_context_budget_revision(self):
        source = region("let attempt=reserve(storage,1,1);")
        analysis = analyze_resources(source)
        output = emit_c(analysis)
        header, adapter = runtime_sources()
        self.assertIn(header, output)
        self.assertIn(adapter, output)
        self.assertLess(output.index(header), output.index("struct tv_s_Allocation {"))
        self.assertLess(output.index("struct tv_s_ByteWrite {"), output.index(adapter))
        self.assertIn("_Alignas(16) uint8_t tv_storage_storage[32];", output)
        context = resource_context(analysis)
        self.assertEqual(context["runtime_inputs"], runtime_identity())
        self.assertEqual(context["bounds"]["allowed_alignments"], [1, 2, 4, 8, 16])
        intrinsics = {fact["name"]: fact for fact in context["intrinsics"]}
        self.assertEqual(set(intrinsics), {"reserve", "release", "read_byte", "write_byte"})
        self.assertEqual(intrinsics["reserve"]["signature"], "fn reserve(region, size: i32, alignment: i32) -> Allocation")
        self.assertEqual(intrinsics["reserve"]["parameters"][0]["passing"], "lexical-capability")
        self.assertEqual(intrinsics["reserve"]["requires"], {"origin_state": "free"})
        self.assertEqual(intrinsics["reserve"]["typed_variants"], ["Granted", "InvalidRequest", "Exhausted"])
        self.assertEqual(intrinsics["release"]["parameters"][0]["effect"], "consume-and-release")
        self.assertEqual(intrinsics["release"]["normal_return"], 0)
        for operation, typ, passing, writes, variants in (
                ("read_byte", "&Block", "borrow-shared", False, ["Value", "OutOfBounds"]),
                ("write_byte", "&mut Block", "borrow-exclusive", True, ["Written", "OutOfBounds", "InvalidByte"])):
            parameter = intrinsics[operation]["parameters"][0]
            self.assertEqual((parameter["type"], parameter["passing"], parameter["borrow_scope"],
                              parameter["may_write"], parameter["escapes"]),
                             (typ, passing, "call", writes, False))
            self.assertEqual(intrinsics[operation]["typed_variants"], variants)
        budget = len(encode(context).encode("utf-8"))
        self.assertEqual(resource_context(analysis, budget, source_hash(source)), context)
        with self.assertRaises(CompileError) as caught:
            resource_context(analysis, budget - 1, source_hash(source))
        self.assertEqual(caught.exception.code, "E0502")
        for options, code in (({"max_bytes": 1}, "E0502"), ({"max_bytes": True}, "E0502"),
                              ({"expected_source_hash": "stale"}, "E0501")):
            with self.assertRaises(CompileError) as caught:
                resource_context(analysis, **options)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(CompileError) as caught:
            emit_c(analysis, freestanding=True)
        self.assertEqual(caught.exception.code, "E0404")


if __name__ == "__main__":
    unittest.main()
