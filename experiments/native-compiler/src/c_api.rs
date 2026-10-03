//! Explicit hosted C11 scalar export boundary, not a foreign import mechanism.
use super::context::{array, object};
use super::*;
const MAX_BYTES: usize = 16 * 1024 * 1024;
fn ctype(ty: &str) -> &str {
    if ty == "i32" { "int32_t" } else { "bool" }
}
fn identifier(value: &str) -> bool {
    let mut chars = value.bytes();
    (1..=64).contains(&value.len())
        && chars
            .next()
            .is_some_and(|b| b.is_ascii_alphabetic() || b == b'_')
        && chars.all(|b| b.is_ascii_alphanumeric() || b == b'_')
}
// Generated strings are numeric byte arrays and source comments are absent.
// Rewrite complete compiler-owned identifiers, never arbitrary source substrings.
fn namespace(code: &str, prefix: &str) -> String {
    let mut out = String::new();
    let mut start = 0;
    let bytes = code.as_bytes();
    while start < bytes.len() {
        let mut end = start + 1;
        if bytes[start].is_ascii_alphabetic() || bytes[start] == b'_' {
            while end < bytes.len() && (bytes[end].is_ascii_alphanumeric() || bytes[end] == b'_') {
                end += 1;
            }
            let token = &code[start..end];
            if let Some(name) = token.strip_prefix("tv_f_") {
                out.push_str(&format!("tv_{prefix}_f_{name}"));
            } else if let Some(name) = token.strip_prefix("tv_s_") {
                out.push_str(&format!("tv_{prefix}_s_{name}"));
            } else {
                out.push_str(token);
            }
        } else {
            out.push(bytes[start] as char);
        }
        start = end;
    }
    out
}
/// Freshly check exact source, then emit a library/header and input identities.
pub fn emit_c_api(
    source: &str,
    module: &str,
    exports: &[String],
    console: bool,
    max_bytes: usize,
) -> Result<String> {
    let program = analyze(source)?;
    if !identifier(module) {
        return Err(error(
            "E1001",
            "C API module must be an ASCII identifier of 1 through 64 bytes",
            0..0,
        ));
    }
    let names: BTreeSet<_> = exports.iter().collect();
    if !(1..=128).contains(&exports.len()) || names.len() != exports.len() {
        return Err(error(
            "E1001",
            "C API requires 1 through 128 distinct function exports",
            0..0,
        ));
    }
    if !(1..=MAX_BYTES).contains(&max_bytes) {
        return Err(error(
            "E1002",
            "C API budget must be between 1 byte and 16 MiB",
            0..0,
        ));
    }
    let prefix = format!("m{}_{module}", module.len());
    let mut facts = Vec::new();
    let mut declarations = Vec::new();
    let mut wrappers = String::new();
    for name in names {
        let Some(function) = program.functions.iter().find(|f| &f.name.text == name) else {
            return Err(error(
                "E1001",
                format!("Unknown C API function {name}"),
                0..0,
            ));
        };
        if !matches!(function.result.text.as_str(), "i32" | "bool")
            || function
                .params
                .iter()
                .any(|(_, t)| !matches!(t.text.as_str(), "i32" | "bool"))
        {
            return Err(error(
                "E1001",
                format!("C API function {name} must use only i32/bool parameters and result"),
                function.name.span.clone(),
            ));
        }
        let symbol = format!("talven_{prefix}_f_{name}");
        let params = function
            .params
            .iter()
            .map(|(n, t)| format!("{} tv_v_{}", ctype(&t.text), n.text))
            .collect::<Vec<_>>()
            .join(", ");
        let params = if params.is_empty() { "void" } else { &params };
        let signature = format!("{} {symbol}({params})", ctype(&function.result.text));
        declarations.push(signature.clone() + ";");
        let args = function
            .params
            .iter()
            .map(|(n, _)| format!("tv_v_{}", n.text))
            .collect::<Vec<_>>()
            .join(", ");
        wrappers.push_str(&format!(
            "{signature} {{\n    return tv_{prefix}_f_{name}({args});\n}}\n"
        ));
        facts.push(object([
            ("name", json(name)),
            ("symbol", json(&symbol)),
            (
                "parameters",
                array(
                    function
                        .params
                        .iter()
                        .map(|(n, t)| object([("name", json(&n.text)), ("type", json(&t.text))])),
                ),
            ),
            ("returns", json(&function.result.text)),
        ]));
    }
    let mut code = namespace(&emit_c_mode(&program, console, true)?, &prefix);
    code.push_str(&wrappers);
    let guard = format!("TALVEN_C_API_{prefix}_V1_INCLUDED");
    let header = format!(
        "/* Talven hosted-c11-scalars-v1; module {module}. */\n#ifndef {guard}\n#define {guard}\n#include <stdint.h>\n#include <stdbool.h>\n{}\n#endif\n",
        declarations.join("\n")
    );
    let result = object([
        ("schema", json("talven.c-api.v1")),
        ("abi_profile", json("hosted-c11-scalars-v1")),
        ("language_profile", json("m1-scalar-mutation-v1")),
        ("compiler_hash", json(&compiler_hash())),
        ("source_hash", json(&source_hash(source))),
        ("target", json("c11-hosted")),
        ("validation", json("frontend-only")),
        ("module", json(module)),
        ("console", console.to_string()),
        ("exports", array(facts)),
        ("header", json(&header)),
        ("header_hash", json(&source_hash(&header))),
        ("c", json(&code)),
        ("c_hash", json(&source_hash(&code))),
    ]) + "\n";
    if result.len() > max_bytes {
        return Err(error("E1002", "C API receipt exceeds byte budget", 0..0));
    }
    Ok(result)
}
