use std::ffi::OsString;
use std::fs::File;
use std::io::{self, Read, Write};
use std::path::Path;
use talven_native::{
    Error, MAX_SOURCE, PROFILE, agent_context, analyze, analyze_measured, emit_c, format_source,
    line_character, receipt, size_error,
};
fn main() {
    std::process::exit(run());
}
fn run() -> i32 {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    if args.first().is_some_and(|a| a == "measure") {
        return measure(&args[1..]);
    }
    if args.len() == 1 && args[0] == "--build-info" {
        let sources = [
            ("Cargo.toml", include_str!("../Cargo.toml")),
            ("Cargo.lock", include_str!("../Cargo.lock")),
            ("build.rs", include_str!("../build.rs")),
            ("src/main.rs", include_str!("main.rs")),
            ("src/lib.rs", include_str!("lib.rs")),
            ("src/format.rs", include_str!("format.rs")),
            ("src/runtime.c", include_str!("runtime.c")),
            ("src/console.c", include_str!("console.c")),
        ]
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
    let valid = args.len() >= 2
        && if args[0] == "context" {
            args[2..].iter().filter(|a| *a == "--compact").count() == 1
                && args[2..].iter().filter(|a| *a == "--json").count() <= 1
                && args[2..].iter().all(|a| a == "--compact" || a == "--json")
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
            "Usage: talven-native check SOURCE [--json] | emit-c SOURCE [--console] | context SOURCE --compact [--json] | fmt SOURCE [--check [--json]]"
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

fn read_source(path: &Path) -> Result<String, Error> {
    let file = open_source(path).map_err(io_error)?;
    if !file.metadata().map_err(io_error)?.is_file() {
        return Err(io_error("Source must be a regular file"));
    }
    let mut bytes = Vec::new();
    file.take((MAX_SOURCE + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(io_error)?;
    if bytes.len() > MAX_SOURCE {
        return Err(size_error());
    }
    String::from_utf8(bytes).map_err(io_error)
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
                return Err(io_error(
                    "Measured output differs from ordinary checked emission",
                ));
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
fn io_error(error: impl std::fmt::Display) -> Error {
    Error {
        code: "E0901",
        message: error.to_string(),
        span: 0..0,
    }
}

// O_NONBLOCK differs by OS and, on Linux, by architecture (for example 0x80 on MIPS and
// 0x4000 on Alpha/SPARC). Only the inspected ABIs are enabled; every other target fails
// explicitly instead of guessing a flag value.
#[cfg(any(
    all(
        target_os = "linux",
        any(target_arch = "x86_64", target_arch = "aarch64")
    ),
    target_os = "macos"
))]
fn open_source(path: &Path) -> io::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    #[cfg(target_os = "linux")]
    const O_NONBLOCK: i32 = 0x800;
    #[cfg(target_os = "macos")]
    const O_NONBLOCK: i32 = 0x4;
    File::options()
        .read(true)
        .custom_flags(O_NONBLOCK)
        .open(path)
}
#[cfg(not(any(
    all(
        target_os = "linux",
        any(target_arch = "x86_64", target_arch = "aarch64")
    ),
    target_os = "macos"
)))]
fn open_source(_: &Path) -> io::Result<File> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "Native experiment opens sources only on Linux x86-64/aarch64 and macOS",
    ))
}
