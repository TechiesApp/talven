//! Bounded facts over one freshly checked source; no stored cache or execution.
use super::*;

pub const SOURCE_FILES: &[(&str, &str)] = &[
    ("Cargo.toml", include_str!("../Cargo.toml")),
    ("Cargo.lock", include_str!("../Cargo.lock")),
    ("build.rs", include_str!("../build.rs")),
    ("src/main.rs", include_str!("main.rs")),
    ("src/lib.rs", include_str!("lib.rs")),
    ("src/format.rs", include_str!("format.rs")),
    ("src/context.rs", include_str!("context.rs")),
    ("src/input.rs", include_str!("input.rs")),
    ("src/edit.rs", include_str!("edit.rs")),
    ("src/c_api.rs", include_str!("c_api.rs")),
    ("src/runtime.c", include_str!("runtime.c")),
    ("src/console.c", include_str!("console.c")),
    ("src/resources.rs", include_str!("resources.rs")),
    (
        "../supplied-storage/runtime.h",
        include_str!("../../supplied-storage/runtime.h"),
    ),
    (
        "../supplied-storage/source-runtime.c",
        include_str!("../../supplied-storage/source-runtime.c"),
    ),
];

/// SHA-256 input identity, not authentication. Bounded callers supply UTF-8 source.
pub fn source_hash(source: &str) -> String {
    sha256(source.as_bytes())
}

/// Length-framed embedded source/build identity, independent of checkout files.
pub fn compiler_hash() -> String {
    let mut framed = b"talven.native-compiler-identity.v1\0".to_vec();
    for (name, value) in SOURCE_FILES.iter().copied().chain([
        ("rustc", env!("TALVEN_RUSTC")),
        ("target", env!("TALVEN_TARGET")),
        ("cargo_profile", env!("TALVEN_PROFILE")),
        ("opt_level", env!("TALVEN_OPT_LEVEL")),
        (
            "settings",
            include_str!(concat!(env!("OUT_DIR"), "/settings.json")),
        ),
    ]) {
        for bytes in [name.as_bytes(), value.as_bytes()] {
            framed.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
            framed.extend_from_slice(bytes);
        }
    }
    sha256(&framed)
}

#[derive(Debug)]
pub struct ContextOptions<'a> {
    pub symbol: Option<&'a str>,
    pub max_bytes: usize,
    pub include_body: bool,
    pub expected_source_hash: Option<&'a str>,
}
impl Default for ContextOptions<'_> {
    fn default() -> Self {
        Self {
            symbol: None,
            max_bytes: 16384,
            include_body: false,
            expected_source_hash: None,
        }
    }
}

pub(crate) fn array(values: impl IntoIterator<Item = String>) -> String {
    format!("[{}]", values.into_iter().collect::<Vec<_>>().join(","))
}
pub(crate) fn object(values: impl IntoIterator<Item = (&'static str, String)>) -> String {
    let values: BTreeMap<_, _> = values.into_iter().collect();
    format!(
        "{{{}}}",
        values
            .into_iter()
            .map(|(key, value)| format!("{}:{value}", json(key)))
            .collect::<Vec<_>>()
            .join(",")
    )
}
fn expressions<'a>(program: &'a Program, function: &Function) -> Vec<&'a Expr> {
    let mut statements: Vec<_> = function.body.iter().collect();
    let mut roots = Vec::new();
    while let Some(stmt) = statements.pop() {
        roots.push(stmt.expr);
        roots.extend(stmt.target);
        statements.extend(&stmt.then);
        statements.extend(&stmt.otherwise);
    }
    let mut result = Vec::new();
    while let Some(index) = roots.pop() {
        let expr = &program.expressions[index];
        result.push(expr);
        roots.extend(expr.children());
    }
    result
}
pub(crate) fn calls(program: &Program, function: &Function) -> BTreeSet<String> {
    expressions(program, function)
        .into_iter()
        .filter_map(|expr| match &expr.kind {
            ExprKind::Call(name, _) => Some(name.clone()),
            _ => None,
        })
        .collect()
}
fn function_fields(function: &Function) -> Vec<(&'static str, String)> {
    let params = function.params.iter().map(|(name, ty)| {
        let mut fields = vec![("name", json(&name.text)), ("type", json(&ty.text))];
        let mode = if ty.text.starts_with("&mut ") {
            Some("exclusive")
        } else if ty.text.starts_with('&') {
            Some("shared")
        } else {
            None
        };
        fields.push((
            "passing",
            json(&mode.map_or_else(
                || {
                    if matches!(ty.text.as_str(), "i32" | "bool" | "str") {
                        "copy".into()
                    } else {
                        "move".into()
                    }
                },
                |mode| format!("borrow-{mode}"),
            )),
        ));
        if let Some(mode) = mode {
            fields.extend([
                ("scope", json("call")),
                ("may_write", (mode == "exclusive").to_string()),
                ("escapes", "false".into()),
            ]);
        }
        object(fields)
    });
    let signature = format!(
        "fn {}({}) -> {}",
        function.name.text,
        function
            .params
            .iter()
            .map(|(n, t)| format!("{}: {}", n.text, t.text))
            .collect::<Vec<_>>()
            .join(", "),
        function.result.text
    );
    vec![
        ("kind", json("function")),
        ("name", json(&function.name.text)),
        ("signature", json(&signature)),
        ("parameters", array(params)),
        ("returns", json(&function.result.text)),
    ]
}
pub(crate) fn function_contract(function: &Function) -> String {
    object(function_fields(function))
}
fn function_fact(program: &Program, function: &Function, source: Option<&str>) -> String {
    let mut fields = function_fields(function);
    fields.push((
        "calls",
        array(calls(program, function).iter().map(|name| json(name))),
    ));
    if let Some(source) = source {
        fields.push((
            "untrusted_source_text",
            json(&source[function.span.clone()]),
        ));
    }
    object(fields)
}

pub(crate) fn record_fact(record: &Record) -> String {
    object([
        ("kind", json("record")),
        ("name", json(&record.name.text)),
        ("ownership", json("move-only")),
        (
            "fields",
            array(
                record
                    .fields
                    .iter()
                    .map(|(n, t)| object([("name", json(&n.text)), ("type", json(&t.text))])),
            ),
        ),
    ])
}

/// Fully checks this exact source before selecting facts. Hash guards precede analysis.
pub fn native_context(source: &str, options: &ContextOptions<'_>) -> Result<String> {
    if source.len() > MAX_SOURCE {
        return Err(size_error());
    }
    let revision = source_hash(source);
    if options
        .expected_source_hash
        .is_some_and(|expected| expected != revision)
    {
        return Err(error(
            "E0501",
            "Source revision changed; request fresh context before editing",
            0..0,
        ));
    }
    // Keep CLI/reference ordering: source analysis errors precede budget/symbol errors.
    let program = analyze(source)?;
    if !(1..=1024 * 1024).contains(&options.max_bytes) {
        return Err(error(
            "E0502",
            "Context budget must be between 1 byte and 1 MiB",
            0..0,
        ));
    }
    let functions: BTreeMap<_, _> = program
        .functions
        .iter()
        .map(|f| (f.name.text.as_str(), f))
        .collect();
    let records: BTreeMap<_, _> = program
        .records
        .iter()
        .map(|r| (r.name.text.as_str(), r))
        .collect();
    if options
        .symbol
        .is_some_and(|name| !functions.contains_key(name) && !records.contains_key(name))
    {
        return Err(error(
            "E0101",
            format!("Unknown symbol {}", options.symbol.unwrap()),
            0..0,
        ));
    }
    let selected: BTreeSet<_> = functions
        .keys()
        .copied()
        .filter(|name| options.symbol.is_none_or(|symbol| symbol == *name))
        .collect();
    let dependencies: BTreeSet<_> = selected
        .iter()
        .flat_map(|name| calls(&program, functions[name]))
        .filter(|name| name != "print" && !selected.contains(name.as_str()))
        .collect();
    let mut used_records = BTreeSet::new();
    if options.symbol.is_none() {
        used_records.extend(records.keys().copied());
    } else if let Some(name) = options.symbol.filter(|name| records.contains_key(name)) {
        used_records.insert(name);
    }
    let mut builtin = false;
    for name in selected
        .iter()
        .copied()
        .chain(dependencies.iter().map(String::as_str))
    {
        let function = functions[name];
        builtin |= calls(&program, function).contains("print");
        for ty in function
            .params
            .iter()
            .map(|(_, t)| t.text.as_str())
            .chain([function.result.text.as_str()])
        {
            let base = ty
                .strip_prefix("&mut ")
                .or_else(|| ty.strip_prefix('&'))
                .unwrap_or(ty);
            if let Some((key, _)) = records.get_key_value(base) {
                used_records.insert(*key);
            }
        }
        if selected.contains(name) {
            for expr in expressions(&program, function) {
                if let Some(Ty::Record(index) | Ty::Borrowed(index, _)) = expr.ty {
                    used_records.insert(program.records[index].name.text.as_str());
                }
            }
        }
    }
    let record_facts = used_records
        .into_iter()
        .map(|name| record_fact(records[name]));
    let builtins = if builtin {
        r#"[{"effects":"blocking stdout writes; partial output possible; host signals unchanged","kind":"builtin","name":"print","parameters":[{"name":"text","passing":"copy","type":"str"}],"requires":"posix-console","result":"0 after all bytes written; 1 on returned write failure or zero progress","returns":"i32","signature":"fn print(text: str) -> i32"}]"#
    } else {
        "[]"
    };
    let result = object([
        ("schema", json("talven.native-context.v1")),
        ("compiler_hash", json(&compiler_hash())),
        ("source_hash", json(&revision)),
        ("profile", json(PROFILE)),
        ("language_profile", json("m1-scalar-mutation-v1")),
        ("target", json("c11-hosted")),
        ("symbol", options.symbol.map_or("null".into(), json)),
        ("include_body", options.include_body.to_string()),
        ("validation", json("frontend-only")),
        (
            "functions",
            array(selected.iter().map(|name| {
                function_fact(
                    &program,
                    functions[name],
                    options.include_body.then_some(source),
                )
            })),
        ),
        (
            "dependencies",
            array(
                dependencies
                    .iter()
                    .map(|name| function_fact(&program, functions[name.as_str()], None)),
            ),
        ),
        ("records", array(record_facts)),
        ("builtins", builtins.into()),
        (
            "required_runtime",
            if program.console {
                "[\"posix-console\"]"
            } else {
                "[]"
            }
            .into(),
        ),
        (
            "callers",
            array(
                functions
                    .iter()
                    .filter(|(_, f)| {
                        options
                            .symbol
                            .is_some_and(|name| calls(&program, f).contains(name))
                    })
                    .map(|(name, _)| json(name)),
            ),
        ),
    ]) + "\n";
    if result.len() > options.max_bytes {
        return Err(error(
            "E0502",
            "Context exceeds byte budget; select one symbol or increase the budget",
            0..0,
        ));
    }
    Ok(result)
}

// FIPS 180-4 SHA-256 compression, used only for deterministic input identities.
// No external process, secret handling, or cryptographic authentication surface.
fn sha256(input: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut data = input.to_vec();
    data.push(0x80);
    while data.len() % 64 != 56 {
        data.push(0);
    }
    data.extend_from_slice(&((input.len() as u64) * 8).to_be_bytes());
    let mut state: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    for block in data.chunks_exact(64) {
        let mut w = [0u32; 64];
        for (word, chunk) in w.iter_mut().zip(block.chunks_exact(4)) {
            *word = u32::from_be_bytes(chunk.try_into().unwrap());
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = state;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let t1 = h
                .wrapping_add(s1)
                .wrapping_add((e & f) ^ (!e & g))
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let t2 = s0.wrapping_add((a & b) ^ (a & c) ^ (b & c));
            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (word, value) in state.iter_mut().zip([a, b, c, d, e, f, g, h]) {
            *word = word.wrapping_add(value);
        }
    }
    state.iter().map(|word| format!("{word:08x}")).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn sha256_known_vectors() {
        assert_eq!(
            sha256(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(
            sha256(&vec![b'a'; 1_000_000]),
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"
        );
    }
}
