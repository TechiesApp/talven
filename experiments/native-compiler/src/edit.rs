//! Read-only snapshots and complete-candidate previews; no atomic application.
use super::context::{array, calls, function_contract, object, record_fact};
use super::*;
use std::path::Path;

const MAX_OUTPUT: usize = 1024 * 1024;
fn valid_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn diagnostic(source: &str, failure: &Error, input: Option<&str>) -> String {
    let mut fields = vec![
        ("code", json(failure.code)),
        ("message", json(&failure.message)),
        ("severity", "1".into()),
        ("source", json("talven-native")),
        (
            "range",
            object([
                ("start", position(source, failure.span.start)),
                ("end", position(source, failure.span.end)),
            ]),
        ),
    ];
    if let Some(input) = input {
        fields.push(("input", json(input)));
    }
    object(fields)
}
fn operation_error(code: &'static str, message: &str, input: &str) -> String {
    diagnostic("", &error(code, message, 0..0), Some(input))
}
fn read_error(failure: &Error, input: &str) -> String {
    diagnostic("", failure, Some(input))
}
fn optional(value: Option<&str>) -> String {
    value.map_or("null".into(), json)
}

/// Obtain exact identities even for invalid syntax; reread detects observed changes.
pub fn snapshot_source(path: &Path, include_source: bool, max_bytes: usize) -> (bool, String) {
    snapshot_with_reader(path, include_source, max_bytes, read_source)
}
fn snapshot_with_reader(
    path: &Path,
    include_source: bool,
    max_bytes: usize,
    mut read: impl FnMut(&Path) -> Result<String>,
) -> (bool, String) {
    let compiler = compiler_hash();
    let mut revision = None;
    let mut text = None;
    let mut diagnostics = Vec::new();
    if !(1..=MAX_OUTPUT).contains(&max_bytes) {
        diagnostics.push(operation_error(
            "E0701",
            "Output budget must be an integer between 1 byte and 1 MiB",
            "request",
        ));
    } else {
        match read(path) {
            Err(failure) => diagnostics.push(read_error(&failure, "source")),
            Ok(source) => {
                revision = Some(source_hash(&source));
                match read(path) {
                    Err(failure) => diagnostics.push(read_error(&failure, "source")),
                    Ok(current) if current != source => diagnostics.push(operation_error(
                        "E0501",
                        "Source changed before snapshot could be returned",
                        "source",
                    )),
                    _ => (),
                }
                text = Some(source);
            }
        }
    }
    let encode = |diagnostics: &[String], echo: bool| {
        let mut fields = vec![
            ("schema", json("talven.native-edit-snapshot.v1")),
            ("ok", diagnostics.is_empty().to_string()),
            ("validation", json("not-run")),
            ("source_hash", optional(revision.as_deref())),
            ("compiler_hash", json(&compiler)),
            ("profile", json(PROFILE)),
            ("language_profile", json("m1-scalar-mutation-v1")),
            (
                "source_bytes",
                text.as_ref().map_or("null".into(), |s| s.len().to_string()),
            ),
            ("diagnostics", array(diagnostics.iter().cloned())),
        ];
        if echo {
            fields.push(("untrusted_source_text", json(text.as_deref().unwrap())));
        }
        object(fields) + "\n"
    };
    let output = encode(&diagnostics, diagnostics.is_empty() && include_source);
    if diagnostics.is_empty() && output.len() > max_bytes {
        diagnostics.push(operation_error(
            "E0703",
            "Snapshot exceeds byte budget",
            "request",
        ));
        return (false, encode(&diagnostics, false));
    }
    (diagnostics.is_empty(), output)
}

struct Preview<'a> {
    ok: bool,
    expected_source: Option<&'a str>,
    expected_compiler: Option<&'a str>,
    compiler: String,
    source: Option<String>,
    candidate: Option<String>,
    base: Option<String>,
    checked_candidate: Option<String>,
    changes: Option<String>,
    diagnostics: Vec<String>,
}
impl Preview<'_> {
    fn clear_analysis(&mut self) {
        self.base = None;
        self.checked_candidate = None;
        self.changes = None;
        self.ok = false;
    }
    fn encode(&self) -> String {
        object([
            ("schema", json("talven.native-edit-validation.v1")),
            ("ok", self.ok.to_string()),
            ("validation", json("frontend-only")),
            ("profile", json(PROFILE)),
            ("language_profile", json("m1-scalar-mutation-v1")),
            ("compiler_hash", json(&self.compiler)),
            ("expected_source_hash", optional(self.expected_source)),
            ("expected_compiler_hash", optional(self.expected_compiler)),
            (
                "source_hash",
                self.source
                    .as_ref()
                    .map_or("null".into(), |s| json(&source_hash(s))),
            ),
            (
                "candidate_hash",
                self.candidate
                    .as_ref()
                    .map_or("null".into(), |s| json(&source_hash(s))),
            ),
            (
                "source_bytes",
                self.source
                    .as_ref()
                    .map_or("null".into(), |s| s.len().to_string()),
            ),
            (
                "candidate_bytes",
                self.candidate
                    .as_ref()
                    .map_or("null".into(), |s| s.len().to_string()),
            ),
            (
                "candidate_changed",
                self.source
                    .as_ref()
                    .zip(self.candidate.as_ref())
                    .map_or("null".into(), |(s, c)| (s != c).to_string()),
            ),
            ("base", self.base.clone().unwrap_or("null".into())),
            (
                "candidate",
                self.checked_candidate.clone().unwrap_or("null".into()),
            ),
            ("changes", self.changes.clone().unwrap_or("null".into())),
            ("diagnostics", array(self.diagnostics.iter().cloned())),
        ]) + "\n"
    }
}
fn frontend(source: &str) -> (Option<Program>, String) {
    match analyze(source) {
        Ok(program) => (Some(program), "{\"diagnostics\":[],\"ok\":true}".into()),
        Err(failure) => (
            None,
            object([
                ("ok", "false".into()),
                ("diagnostics", array([diagnostic(source, &failure, None)])),
            ]),
        ),
    }
}
fn contracts(program: &Program) -> BTreeMap<(&str, &str), String> {
    program
        .functions
        .iter()
        .map(|f| (("function", f.name.text.as_str()), function_contract(f)))
        .chain(
            program
                .records
                .iter()
                .map(|r| (("record", r.name.text.as_str()), record_fact(r))),
        )
        .collect()
}
fn changes(before: &Program, after: &Program) -> String {
    let base = contracts(before);
    let candidate = contracts(after);
    let before_calls: BTreeMap<_, _> = before
        .functions
        .iter()
        .map(|f| (f.name.text.as_str(), calls(before, f)))
        .collect();
    let after_calls: BTreeMap<_, _> = after
        .functions
        .iter()
        .map(|f| (f.name.text.as_str(), calls(after, f)))
        .collect();
    object([
        (
            "added",
            array(
                candidate
                    .iter()
                    .filter(|(key, _)| !base.contains_key(*key))
                    .map(|(_, fact)| fact.clone()),
            ),
        ),
        (
            "removed",
            array(
                base.iter()
                    .filter(|(key, _)| !candidate.contains_key(*key))
                    .map(|(_, fact)| fact.clone()),
            ),
        ),
        (
            "contracts_changed",
            array(base.iter().filter_map(|((kind, name), fact)| {
                candidate
                    .get(&(*kind, *name))
                    .filter(|current| *current != fact)
                    .map(|current| {
                        object([
                            ("kind", json(kind)),
                            ("name", json(name)),
                            ("before", fact.clone()),
                            ("after", current.clone()),
                        ])
                    })
            })),
        ),
        (
            "calls_changed",
            array(before_calls.iter().filter_map(|(name, calls)| {
                after_calls
                    .get(name)
                    .filter(|current| *current != calls)
                    .map(|current| {
                        object([
                            ("name", json(name)),
                            ("before", array(calls.iter().map(|n| json(n)))),
                            ("after", array(current.iter().map(|n| json(n)))),
                        ])
                    })
            })),
        ),
    ])
}

/// Validate a complete candidate against the same embedded compiler and observed source.
pub fn validate_edit(
    source_path: &Path,
    candidate_path: &Path,
    expected_source: &str,
    expected_compiler: &str,
    max_bytes: usize,
) -> (bool, String) {
    validate_with_reader(
        source_path,
        candidate_path,
        expected_source,
        expected_compiler,
        max_bytes,
        read_source,
    )
}
fn validate_with_reader(
    source_path: &Path,
    candidate_path: &Path,
    expected_source: &str,
    expected_compiler: &str,
    max_bytes: usize,
    mut read: impl FnMut(&Path) -> Result<String>,
) -> (bool, String) {
    let mut preview = Preview {
        ok: false,
        expected_source: valid_hash(expected_source).then_some(expected_source),
        expected_compiler: valid_hash(expected_compiler).then_some(expected_compiler),
        compiler: compiler_hash(),
        source: None,
        candidate: None,
        base: None,
        checked_candidate: None,
        changes: None,
        diagnostics: Vec::new(),
    };
    let attempt = (|| -> std::result::Result<(), String> {
        if preview.expected_source.is_none()
            || preview.expected_compiler.is_none()
            || !(1..=MAX_OUTPUT).contains(&max_bytes)
        {
            return Err(operation_error(
                "E0701",
                "Expected hashes must be 64 lowercase hexadecimal characters and output budget must be between 1 byte and 1 MiB",
                "request",
            ));
        }
        if expected_compiler != preview.compiler {
            return Err(operation_error(
                "E0702",
                "Compiler revision changed; request a fresh snapshot",
                "compiler",
            ));
        }
        preview.source = Some(read(source_path).map_err(|e| read_error(&e, "source"))?);
        if source_hash(preview.source.as_deref().unwrap()) != expected_source {
            return Err(operation_error(
                "E0501",
                "Source revision changed; request a fresh snapshot",
                "source",
            ));
        }
        preview.candidate = Some(read(candidate_path).map_err(|e| read_error(&e, "candidate"))?);
        let (before, base) = frontend(preview.source.as_deref().unwrap());
        let (after, candidate) = frontend(preview.candidate.as_deref().unwrap());
        preview.base = Some(base);
        preview.checked_candidate = Some(candidate);
        preview.changes = before
            .as_ref()
            .zip(after.as_ref())
            .map(|(a, b)| changes(a, b));
        // Read both before deciding, preserving the observed-input contract.
        let current_source = read(source_path);
        let current_candidate = read(candidate_path);
        let source = current_source.map_err(|e| read_error(&e, "source"))?;
        let candidate = current_candidate.map_err(|e| read_error(&e, "candidate"))?;
        if source != *preview.source.as_ref().unwrap()
            || candidate != *preview.candidate.as_ref().unwrap()
        {
            let input = if source != *preview.source.as_ref().unwrap() {
                "source"
            } else {
                "candidate"
            };
            return Err(operation_error(
                "E0501",
                if input == "source" {
                    "Source changed during validation"
                } else {
                    "Candidate changed during validation"
                },
                input,
            ));
        }
        // Embedded identities cannot change within this loaded process.
        preview.ok = after.is_some();
        Ok(())
    })();
    if let Err(failure) = attempt {
        preview.clear_analysis();
        preview.diagnostics.push(failure);
    }
    let output = preview.encode();
    if preview.diagnostics.is_empty() && output.len() > max_bytes {
        preview.clear_analysis();
        preview.diagnostics.push(operation_error(
            "E0703",
            "Validation receipt exceeds byte budget",
            "request",
        ));
        return (false, preview.encode());
    }
    (preview.ok, output)
}

#[cfg(test)]
mod tests {
    use super::*;
    const BASE: &str = "fn f()->i32{return 0;}";
    #[test]
    fn observed_snapshot_changes_are_rejected() {
        let mut calls = 0;
        let (ok, output) = snapshot_with_reader(Path::new("source"), true, 16384, |_| {
            calls += 1;
            Ok(if calls == 1 { BASE } else { "changed" }.into())
        });
        assert!(!ok);
        assert!(output.contains("E0501"));
        assert!(!output.contains("untrusted_source_text"));
    }
    #[test]
    fn observed_either_input_change_clears_all_analysis() {
        for changed_read in [3, 4] {
            let mut count = 0;
            let (ok, output) = validate_with_reader(
                Path::new("source"),
                Path::new("candidate"),
                &source_hash(BASE),
                &compiler_hash(),
                16384,
                |_| {
                    count += 1;
                    Ok(if count == changed_read {
                        "changed"
                    } else {
                        BASE
                    }
                    .into())
                },
            );
            assert!(!ok);
            assert!(output.contains("E0501"));
            assert!(output.contains("\"base\":null"));
            assert!(output.contains("\"candidate\":null"));
            assert!(output.contains("\"changes\":null"));
        }
    }
    #[test]
    fn reread_failures_clear_analysis_and_source_echo() {
        let mut count = 0;
        let (ok, output) = snapshot_with_reader(Path::new("source"), true, 16384, |_| {
            count += 1;
            if count == 2 {
                Err(error("E0901", "read failed", 0..0))
            } else {
                Ok(BASE.into())
            }
        });
        assert!(!ok);
        assert!(output.contains("E0901"));
        assert!(!output.contains("untrusted_source_text"));
        for failed_read in [3, 4] {
            let mut count = 0;
            let (ok, output) = validate_with_reader(
                Path::new("source"),
                Path::new("candidate"),
                &source_hash(BASE),
                &compiler_hash(),
                16384,
                |_| {
                    count += 1;
                    if count == failed_read {
                        Err(error("E0901", "read failed", 0..0))
                    } else {
                        Ok(BASE.into())
                    }
                },
            );
            assert!(!ok);
            assert!(output.contains("E0901"));
            assert!(output.contains("\"base\":null"));
            assert!(output.contains("\"candidate\":null"));
            assert!(output.contains("\"changes\":null"));
        }
    }
    #[test]
    fn stale_guards_never_read_the_candidate() {
        let (ok, output) = validate_with_reader(
            Path::new("source"),
            Path::new("candidate"),
            &"0".repeat(64),
            &compiler_hash(),
            16384,
            |path| {
                assert_eq!(path, Path::new("source"));
                Ok(BASE.into())
            },
        );
        assert!(!ok);
        assert!(output.contains("E0501"));
        let (ok, output) = validate_with_reader(
            Path::new("source"),
            Path::new("candidate"),
            &source_hash(BASE),
            &"0".repeat(64),
            16384,
            |_| panic!("stale compiler must not read"),
        );
        assert!(!ok);
        assert!(output.contains("E0702"));
    }
}
