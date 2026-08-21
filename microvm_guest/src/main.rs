use serde_json::{Map, Value};
use std::collections::BTreeSet;
use std::env;
use std::io::{self, Read, Write};
use std::mem;
use std::os::fd::{FromRawFd, RawFd};

const VMADDR_CID_ANY: u32 = 0xffff_ffff;
const DEFAULT_PORT: u32 = 5000;
const MAX_MESSAGE: usize = 1024 * 1024;

fn vsock_listener(port: u32) -> io::Result<std::fs::File> {
    unsafe {
        let fd: RawFd = libc::socket(libc::AF_VSOCK, libc::SOCK_STREAM | libc::SOCK_CLOEXEC, 0);
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }

        let addr = libc::sockaddr_vm {
            svm_family: libc::AF_VSOCK as libc::sa_family_t,
            svm_reserved1: 0,
            svm_port: port,
            svm_cid: VMADDR_CID_ANY,
            svm_zero: [0; 4],
        };
        let rc = libc::bind(
            fd,
            &addr as *const libc::sockaddr_vm as *const libc::sockaddr,
            mem::size_of::<libc::sockaddr_vm>() as libc::socklen_t,
        );
        if rc != 0 {
            let err = io::Error::last_os_error();
            libc::close(fd);
            return Err(err);
        }
        if libc::listen(fd, 1) != 0 {
            let err = io::Error::last_os_error();
            libc::close(fd);
            return Err(err);
        }
        Ok(std::fs::File::from_raw_fd(fd))
    }
}

fn accept_one(listener: &std::fs::File) -> io::Result<std::fs::File> {
    unsafe {
        let fd = libc::accept4(
            std::os::fd::AsRawFd::as_raw_fd(listener),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            libc::SOCK_CLOEXEC,
        );
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(std::fs::File::from_raw_fd(fd))
    }
}

fn read_frame(stream: &mut std::fs::File) -> io::Result<Vec<u8>> {
    let mut header = [0u8; 4];
    stream.read_exact(&mut header)?;
    let length = u32::from_be_bytes(header) as usize;
    if length == 0 || length > MAX_MESSAGE {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "message length outside bounds"));
    }
    let mut body = vec![0u8; length];
    stream.read_exact(&mut body)?;
    Ok(body)
}

fn write_frame(stream: &mut std::fs::File, body: &[u8]) -> io::Result<()> {
    if body.len() > MAX_MESSAGE {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "response exceeds message bound"));
    }
    stream.write_all(&(body.len() as u32).to_be_bytes())?;
    stream.write_all(body)?;
    stream.flush()
}

fn require_string(map: &Map<String, Value>, key: &str) -> Result<String, String> {
    match map.get(key).and_then(Value::as_str) {
        Some(value) if !value.is_empty() => Ok(value.to_owned()),
        _ => Err(format!("missing or invalid {key}")),
    }
}

fn validate_effect(value: Value) -> Result<Value, String> {
    let object = value
        .as_object()
        .ok_or_else(|| "effect must be a JSON object".to_string())?;

    let expected: BTreeSet<&str> = [
        "provider",
        "operation",
        "owner",
        "repo",
        "branch",
        "path",
        "expected_blob_sha",
        "content_b64",
        "commit_message",
    ]
    .into_iter()
    .collect();
    let observed: BTreeSet<&str> = object.keys().map(String::as_str).collect();
    if observed != expected {
        return Err("effect object contains missing or unexpected fields".to_string());
    }

    if require_string(object, "provider")? != "github" {
        return Err("provider must be github".to_string());
    }
    if require_string(object, "operation")? != "github.file.update" {
        return Err("operation must be github.file.update".to_string());
    }
    require_string(object, "owner")?;
    require_string(object, "repo")?;
    require_string(object, "branch")?;
    require_string(object, "expected_blob_sha")?;
    require_string(object, "content_b64")?;
    require_string(object, "commit_message")?;

    let path = require_string(object, "path")?;
    if path.starts_with('/') || path.split('/').any(|part| part == "..") {
        return Err("path escapes repository boundary".to_string());
    }

    Ok(Value::Object(object.clone()))
}

fn run() -> Result<(), String> {
    let port = env::var("VEKLOM_VSOCK_PORT")
        .ok()
        .and_then(|raw| raw.parse::<u32>().ok())
        .unwrap_or(DEFAULT_PORT);
    if !(1024..=65535).contains(&port) {
        return Err("VEKLOM_VSOCK_PORT outside allowed range".to_string());
    }

    let listener = vsock_listener(port).map_err(|err| format!("vsock listen failed: {err}"))?;
    let mut stream = accept_one(&listener).map_err(|err| format!("vsock accept failed: {err}"))?;
    let request = read_frame(&mut stream).map_err(|err| format!("request framing failed: {err}"))?;
    let parsed: Value = serde_json::from_slice(&request).map_err(|_| "request is not valid JSON".to_string())?;
    let validated = validate_effect(parsed)?;
    let response = serde_json::to_vec(&validated).map_err(|_| "response serialization failed".to_string())?;
    write_frame(&mut stream, &response).map_err(|err| format!("response framing failed: {err}"))?;
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("lockerphycer-cell-agent: {error}");
        std::process::exit(70);
    }
}
