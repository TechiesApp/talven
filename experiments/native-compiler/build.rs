use std::{collections::BTreeMap, env, fs, path::PathBuf, process::Command};
fn json(s: &str) -> String {
    let mut out = String::from("\"");
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            ch if ch < ' ' => out.push_str(&format!("\\u{:04x}", ch as u32)),
            ch => out.push(ch),
        }
    }
    out.push('"');
    out
}
fn main() {
    let output = Command::new(env::var("RUSTC").unwrap())
        .arg("--version")
        .output()
        .unwrap();
    assert!(output.status.success());
    println!(
        "cargo:rustc-env=TALVEN_RUSTC={}",
        String::from_utf8(output.stdout).unwrap().trim()
    );
    for key in ["TARGET", "PROFILE", "OPT_LEVEL"] {
        println!("cargo:rustc-env=TALVEN_{key}={}", env::var(key).unwrap());
    }
    let mut settings = BTreeMap::new();
    for key in [
        "CARGO_ENCODED_RUSTFLAGS",
        "RUSTFLAGS",
        "DEBUG",
        "CARGO_CFG_TARGET_FEATURE",
    ] {
        settings.insert(key.to_string(), env::var(key).unwrap_or_default());
        println!("cargo:rerun-if-env-changed={key}");
    }
    for (key, value) in env::vars().filter(|(k, _)| k.starts_with("CARGO_PROFILE_")) {
        println!("cargo:rerun-if-env-changed={key}");
        settings.insert(key, value);
    }
    let data = settings
        .iter()
        .map(|(k, v)| format!("{}:{}", json(k), json(v)))
        .collect::<Vec<_>>()
        .join(",");
    fs::write(
        PathBuf::from(env::var_os("OUT_DIR").unwrap()).join("settings.json"),
        format!("{{{data}}}"),
    )
    .unwrap();
    println!("cargo:rerun-if-changed=build.rs");
}
