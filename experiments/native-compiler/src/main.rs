use std::ffi::OsString;
use std::io::{self, Write};
use std::path::Path;
use talven_native::{
    ContextOptions, Error, PROFILE, SOURCE_FILES, agent_context, analyze, analyze_measured, emit_c,
    format_source, line_character, native_context, read_source, receipt,
};
fn main() {
    std::process::exit(run());
}
fn run() -> i32 {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    if args.first().is_some_and(|a| a == "edit") {
        return edit(&args[1..]);
    }
    if args.first().is_some_and(|a| a == "measure") {
        return measure(&args[1..]);
    }
    if args.len() == 1 && args[0] == "--build-info" {
        let sources = SOURCE_FILES
            .iter()
            .map(|(name, contents)| {
                format!(
                    "{}:{}",
                    talven_native::json(name),
                    talven_native::json(contents)
                )
            })
            .collect::<Vec<_>>()
            .join(",");
        let output = format!(
            "{{\"rustc\":{},\"target\":{},\"cargo_profile\":{},\"opt_level\":{},\"settings\":{},\"source_files\":{{{sources}}}}}\n",
            talven_native::json(env!("TALVEN_RUSTC")),
            talven_native::json(env!("TALVEN_TARGET")),
            talven_native::json(env!("TALVEN_PROFILE")),
            talven_native::json(env!("TALVEN_OPT_LEVEL")),
            include_str!(concat!(env!("OUT_DIR"), "/settings.json"))
        );
        return if io::stdout().lock().write_all(output.as_bytes()).is_ok() {
            0
        } else {
            1
        };
    }
    if args.len() == 1 && args[0] == "--version" {
        println!("Talven native experiment 0.1.0 ({PROFILE})");
        return 0;
    }
    let context_request = if args.first().is_some_and(|a| a == "context") {
        context_options(&args)
    } else {
        None
    };
    let valid = args.len() >= 2
        && if args[0] == "context" {
            context_request.is_some()
        } else if args[0] == "fmt" {
            args[2..].iter().filter(|a| *a == "--check").count() <= 1
                && args[2..].iter().filter(|a| *a == "--json").count() <= 1
                && args[2..].iter().all(|a| a == "--check" || a == "--json")
                && (!args[2..].iter().any(|a| a == "--json")
                    || args[2..].iter().any(|a| a == "--check"))
        } else {
            (args[0] == "check" || args[0] == "emit-c")
                && args[2..].iter().all(|a| a == "--json" || a == "--console")
                && (args[0] != "emit-c" || args[2..].iter().all(|a| a != "--json"))
        };
    if !valid {
        eprintln!(
            "Usage: talven-native check SOURCE [--json] | emit-c SOURCE [--console] | context SOURCE [--compact | --symbol NAME] [--max-bytes N] [--include-body] [--expect-source-hash HASH] [--json] | fmt SOURCE [--check [--json]]"
        );
        return 2;
    }
    let structured = args[0] == "context" || args[2..].iter().any(|a| a == "--json");
    let console = args[2..].iter().any(|a| a == "--console");
    let mut source = String::new();
    let outcome: Result<String, Error> = (|| {
        source = read_source(Path::new(&args[1]))?;
        if args[0] == "fmt" {
            let formatted = format_source(&source)?;
            return if args[2..].iter().any(|a| a == "--check") {
                if formatted != source {
                    Err(Error {
                        code: "E0601",
                        message: "Source is not canonically formatted; run talven-native fmt to preview the layout".into(),
                        span: 0..0,
                    })
                } else if structured {
                    Ok(receipt(&source, None))
                } else {
                    Ok("Formatting check passed\n".into())
                }
            } else {
                Ok(formatted)
            };
        }
        if args[0] == "context" && !context_request.as_ref().unwrap().0 {
            return native_context(&source, &context_request.as_ref().unwrap().1);
        }
        let program = analyze(&source)?;
        if args[0] == "emit-c" {
            emit_c(&program, console)
        } else if args[0] == "context" {
            Ok(agent_context(&program))
        } else if structured {
            Ok(receipt(&source, None))
        } else {
            Ok(format!("Check passed ({PROFILE})\n"))
        }
    })();
    match outcome {
        Ok(output) => {
            if io::stdout().lock().write_all(output.as_bytes()).is_ok() {
                0
            } else {
                1
            }
        }
        Err(error) => {
            if structured {
                let _ = io::stdout()
                    .lock()
                    .write_all(receipt(&source, Some(&error)).as_bytes());
            } else {
                // The reference CLI's one-based line:character prefix.
                let (line, character) = line_character(&source, error.span.start);
                eprintln!(
                    "{}:{}:{}: {}: {}",
                    Path::new(&args[1]).display(),
                    line + 1,
                    character + 1,
                    error.code,
                    error.message
                );
            }
            1
        }
    }
}

// Parse the complete request before source I/O; reject duplicates and unsupported combinations.
fn context_options(args: &[OsString]) -> Option<(bool, ContextOptions<'_>)> {
    if args.len() < 2 {
        return None;
    }
    let mut options = ContextOptions::default();
    let mut seen = std::collections::BTreeSet::new();
    let mut index = 2;
    while index < args.len() {
        let flag = args[index].to_str()?;
        if !seen.insert(flag) {
            return None;
        }
        match flag {
            "--compact" | "--json" => (),
            "--include-body" => options.include_body = true,
            "--symbol" | "--max-bytes" | "--expect-source-hash" => {
                index += 1;
                let value = args.get(index)?.to_str()?;
                match flag {
                    "--symbol" if !value.is_empty() && !value.starts_with("--") => {
                        options.symbol = Some(value)
                    }
                    "--max-bytes"
                        if !value.is_empty() && value.bytes().all(|b| b.is_ascii_digit()) =>
                    {
                        options.max_bytes = value.parse().ok()?
                    }
                    "--expect-source-hash"
                        if value.len() == 64
                            && value
                                .bytes()
                                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) =>
                    {
                        options.expected_source_hash = Some(value)
                    }
                    _ => return None,
                }
            }
            _ => return None,
        }
        index += 1;
    }
    let compact = seen.contains("--compact");
    if compact
        && seen
            .iter()
            .any(|flag| !matches!(*flag, "--compact" | "--json"))
    {
        return None;
    }
    Some((compact, options))
}

fn measure(args: &[OsString]) -> i32 {
    let usage = || {
        eprintln!("Usage: talven-native measure SOURCE [--iterations 1..100] [--warmups 0..10]");
        2
    };
    if args.is_empty() || args.len().is_multiple_of(2) {
        return usage();
    }
    let (mut iterations, mut warmups) = (10_usize, 1_usize);
    let (mut seen_iterations, mut seen_warmups) = (false, false);
    for pair in args[1..].chunks_exact(2) {
        let Some(value) = pair[1].to_str().and_then(|s| {
            if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
                None
            } else {
                s.parse::<usize>().ok()
            }
        }) else {
            return usage();
        };
        if pair[0] == "--iterations" && !seen_iterations && (1..=100).contains(&value) {
            iterations = value;
            seen_iterations = true;
        } else if pair[0] == "--warmups" && !seen_warmups && value <= 10 {
            warmups = value;
            seen_warmups = true;
        } else {
            return usage();
        }
    }
    let mut source = String::new();
    let outcome: Result<String, Error> = (|| {
        source = read_source(Path::new(&args[0]))?;
        let baseline = emit_c(&analyze(&source)?, true)?;
        let mut samples = Vec::new();
        for index in 0..warmups + iterations {
            let started = std::time::Instant::now();
            let (program, timing) = analyze_measured(&source)?;
            let analysis_ns = started.elapsed().as_nanos();
            let started = std::time::Instant::now();
            let generated = emit_c(&program, true)?;
            let emit_ns = started.elapsed().as_nanos();
            if generated != baseline {
                return Err(Error {
                    code: "E0901",
                    message: "Measured output differs from ordinary checked emission".into(),
                    span: 0..0,
                });
            }
            let phase = if index < warmups {
                "warmup"
            } else {
                "measured"
            };
            samples.push(format!(
                "{{\"phase\":\"{phase}\",\"parse_ns\":{},\"check_ns\":{},\"analysis_ns\":{analysis_ns},\"emit_ns\":{emit_ns}}}",
                timing.parse_ns, timing.check_ns
            ));
        }
        Ok(format!(
            "{{\"schema\":\"talven.native-inprocess.v1\",\"complete\":true,\"profile\":{},\"source\":{},\"source_bytes\":{},\"console\":true,\"preflight_analysis\":1,\"iterations\":{iterations},\"warmups\":{warmups},\"samples\":[{}],\"generated_c\":{}}}\n",
            talven_native::json(PROFILE),
            talven_native::json(&source),
            source.len(),
            samples.join(","),
            talven_native::json(&baseline)
        ))
    })();
    match outcome {
        Ok(output) => {
            if io::stdout().lock().write_all(output.as_bytes()).is_ok() {
                0
            } else {
                1
            }
        }
        Err(error) => {
            let _ = io::stdout()
                .lock()
                .write_all(receipt(&source, Some(&error)).as_bytes());
            1
        }
    }
}
fn edit(args: &[OsString]) -> i32 {
    let usage = || {
        eprintln!(
            "Usage: talven-native edit snapshot SOURCE [--include-source] [--max-bytes N] | edit validate SOURCE --candidate FILE --expect-source-hash HASH --expect-compiler-hash HASH [--max-bytes N]"
        );
        2
    };
    if args.len() < 2 || (args[0] != "snapshot" && args[0] != "validate") {
        return usage();
    }
    let snapshot = args[0] == "snapshot";
    let mut include_source = false;
    let mut max_bytes = 16384;
    let (mut candidate, mut source_hash, mut compiler_hash) = (None, None, None);
    let mut seen = std::collections::BTreeSet::new();
    let mut index = 2;
    while index < args.len() {
        let Some(flag) = args[index].to_str() else {
            return usage();
        };
        if !seen.insert(flag) {
            return usage();
        }
        if flag == "--include-source" && snapshot {
            include_source = true;
        } else if flag == "--max-bytes"
            || (!snapshot
                && matches!(
                    flag,
                    "--candidate" | "--expect-source-hash" | "--expect-compiler-hash"
                ))
        {
            index += 1;
            let Some(value) = args.get(index) else {
                return usage();
            };
            match flag {
                "--candidate" => candidate = Some(value),
                "--expect-source-hash" => source_hash = value.to_str(),
                "--expect-compiler-hash" => compiler_hash = value.to_str(),
                "--max-bytes" => {
                    let Some(parsed) = value
                        .to_str()
                        .filter(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
                        .and_then(|s| s.parse::<usize>().ok())
                    else {
                        return usage();
                    };
                    max_bytes = parsed;
                }
                _ => return usage(),
            }
        } else {
            return usage();
        }
        index += 1;
    }
    let (ok, output) = if snapshot {
        talven_native::snapshot_source(Path::new(&args[1]), include_source, max_bytes)
    } else {
        let (Some(candidate), Some(source_hash), Some(compiler_hash)) =
            (candidate, source_hash, compiler_hash)
        else {
            return usage();
        };
        talven_native::validate_edit(
            Path::new(&args[1]),
            Path::new(candidate),
            source_hash,
            compiler_hash,
            max_bytes,
        )
    };
    if io::stdout().lock().write_all(output.as_bytes()).is_err() || !ok {
        1
    } else {
        0
    }
}
