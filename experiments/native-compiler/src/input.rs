//! Shared bounded regular-file source reads for native CLI and edit previews.
use super::{Error, MAX_SOURCE, Result, size_error};
use std::fs::File;
use std::io::{self, Read};
use std::path::Path;

pub fn read_source(path: &Path) -> Result<String> {
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
