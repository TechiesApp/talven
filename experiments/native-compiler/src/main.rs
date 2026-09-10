use std::ffi::OsString;
use std::fs::File;
use std::io::{self, Read, Write};
use std::path::Path;
use talven_native::{Error, MAX_SOURCE, PROFILE, analyze, emit_c, receipt};
fn main() {
    std::process::exit(run());
}
fn run() -> i32 {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    if args.len() == 1 && args[0] == "--build-info" {
        let sources = [
            ("Cargo.toml", include_str!("../Cargo.toml")),
            ("Cargo.lock", include_str!("../Cargo.lock")),
            ("build.rs", include_str!("../build.rs")),
            ("src/main.rs", include_str!("main.rs")),
            ("src/lib.rs", include_str!("lib.rs")),
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
    if args.len() < 2
        || !(args[0] == "check" || args[0] == "emit-c")
        || args[2..].iter().any(|a| a != "--json" && a != "--console")
        || (args[0] == "emit-c" && args[2..].iter().any(|a| a == "--json"))
    {
        eprintln!("Usage: talven-native check SOURCE [--json] | emit-c SOURCE [--console]");
        return 2;
    }
    let structured = args[2..].iter().any(|a| a == "--json");
    let console = args[2..].iter().any(|a| a == "--console");
    let mut source = String::new();
    let outcome: Result<String, Error> = (|| {
        let file = open_source(Path::new(&args[1])).map_err(io_error)?;
        if !file.metadata().map_err(io_error)?.is_file() {
            return Err(io_error("Source must be a regular file"));
        }
        let mut bytes = Vec::new();
        file.take((MAX_SOURCE + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(io_error)?;
        if bytes.len() > MAX_SOURCE {
            return Err(Error {
                code: "E0005",
                message: "Source exceeds 256 KiB".into(),
                span: 0..0,
            });
        }
        source = String::from_utf8(bytes).map_err(io_error)?;
        let program = analyze(&source)?;
        if args[0] == "emit-c" {
            emit_c(&program, console)
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
                eprintln!(
                    "{}: {}: {}",
                    Path::new(&args[1]).display(),
                    error.code,
                    error.message
                );
            }
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

// O_NONBLOCK values for the two inspected host ABIs. Other OSes fail explicitly.
#[cfg(any(target_os = "linux", target_os = "macos"))]
fn open_source(path: &Path) -> io::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    #[cfg(target_os = "linux")]
    let nonblocking = 0x800;
    #[cfg(target_os = "macos")]
    let nonblocking = 0x4;
    File::options()
        .read(true)
        .custom_flags(nonblocking)
        .open(path)
}
#[cfg(not(any(target_os = "linux", target_os = "macos")))]
fn open_source(_: &Path) -> io::Result<File> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "Native experiment requires Linux or macOS file opening",
    ))
}
