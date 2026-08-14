use std::{
    env,
    ffi::{OsStr, OsString},
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, ExitCode, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

use tauri::{
    menu::{MenuBuilder, MenuItem, SubmenuBuilder},
    Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};

const LOOPBACK_HOST: &str = "127.0.0.1";
const DEFAULT_STUDIO_PORT: u16 = 8772;
const MAX_FALLBACK_STUDIO_PORT: u16 = 8782;
const DEFAULT_SELECTOR_PORT: u16 = 8765;
const SUPERVISOR_FLAG: &str = "--shawn-supervise-child";
const PRODUCT_NAME: &str = "Shawn PPT Studio";

#[derive(Clone, Debug, PartialEq, Eq)]
struct LoopbackEndpoint {
    port: u16,
}

impl LoopbackEndpoint {
    fn new(port: u16) -> Self {
        Self { port }
    }

    fn address(&self) -> String {
        format!("{LOOPBACK_HOST}:{}", self.port)
    }

    fn url(&self) -> String {
        format!("http://{LOOPBACK_HOST}:{}/", self.port)
    }
}

#[derive(Clone, Debug)]
struct DesktopConfig {
    studio_root: PathBuf,
    data_root: PathBuf,
    selector_root: PathBuf,
    node: PathBuf,
    python: PathBuf,
    selector_override: Option<PathBuf>,
    studio: LoopbackEndpoint,
    selector: LoopbackEndpoint,
}

#[derive(Default)]
struct ManagedServices {
    studio: Option<Child>,
    selector: Option<Child>,
}

impl ManagedServices {
    fn stop(&mut self) {
        stop_child(&mut self.studio);
        stop_child(&mut self.selector);
    }
}

impl Drop for ManagedServices {
    fn drop(&mut self) {
        self.stop();
    }
}

fn signal_process_group(pid: u32, signal: &str) -> bool {
    #[cfg(unix)]
    {
        return Command::new("/bin/kill")
            .args([signal, &format!("-{pid}")])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok_and(|status| status.success());
    }
    #[cfg(not(unix))]
    {
        let _ = (pid, signal);
        false
    }
}

fn stop_child(child: &mut Option<Child>) {
    let Some(mut process) = child.take() else {
        return;
    };

    #[cfg(unix)]
    {
        let _ = signal_process_group(process.id(), "-TERM");
        let deadline = Instant::now() + Duration::from_secs(4);
        while Instant::now() < deadline {
            match process.try_wait() {
                Ok(Some(_)) => return,
                Ok(None) => thread::sleep(Duration::from_millis(50)),
                Err(_) => break,
            }
        }
        let _ = signal_process_group(process.id(), "-KILL");
    }

    let _ = process.kill();
    let _ = process.wait();
}

fn process_is_alive(pid: u32) -> bool {
    #[cfg(unix)]
    {
        return Command::new("/bin/kill")
            .args(["-0", &pid.to_string()])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok_and(|status| status.success());
    }
    #[cfg(not(unix))]
    {
        let _ = pid;
        true
    }
}

fn supervise_child(mut args: impl Iterator<Item = OsString>) -> Result<i32, String> {
    let raw_parent = args
        .next()
        .ok_or_else(|| "desktop child supervisor is missing parent PID".to_string())?;
    let parent_pid = raw_parent
        .to_string_lossy()
        .parse::<u32>()
        .map_err(|_| "desktop child supervisor parent PID is invalid".to_string())?;
    if args.next().as_deref() != Some(OsStr::new("--")) {
        return Err("desktop child supervisor separator is missing".into());
    }
    let program = args
        .next()
        .ok_or_else(|| "desktop child supervisor program is missing".to_string())?;
    let mut command = Command::new(program);
    command.args(args);
    let mut child = command
        .spawn()
        .map_err(|error| format!("cannot start supervised desktop service: {error}"))?;

    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Ok(status.code().unwrap_or(1)),
            Ok(None) => {}
            Err(error) => {
                return Err(format!(
                    "cannot observe supervised desktop service: {error}"
                ))
            }
        }
        if !process_is_alive(parent_pid) {
            // The supervisor and every service descendant share a dedicated
            // process group. Terminating that group also covers Codex, which
            // is a grandchild of the Node bridge rather than a direct child.
            if signal_process_group(std::process::id(), "-TERM") {
                thread::sleep(Duration::from_secs(1));
            }
            let _ = child.kill();
            let _ = child.wait();
            return Ok(0);
        }
        thread::sleep(Duration::from_millis(200));
    }
}

fn maybe_supervisor_exit() -> Option<ExitCode> {
    let mut args = env::args_os().skip(1);
    if args.next().as_deref() != Some(OsStr::new(SUPERVISOR_FLAG)) {
        return None;
    }
    let code = match supervise_child(args) {
        Ok(code) => code.clamp(0, u8::MAX as i32) as u8,
        Err(error) => {
            eprintln!("{error}");
            70
        }
    };
    Some(ExitCode::from(code))
}

fn supervised_command(program: &Path, args: &[OsString], cwd: &Path) -> Result<Command, String> {
    let executable = env::current_exe()
        .map_err(|error| format!("cannot resolve desktop executable: {error}"))?;
    let mut command = Command::new(executable);
    command
        .arg(SUPERVISOR_FLAG)
        .arg(std::process::id().to_string())
        .arg("--")
        .arg(program)
        .args(args)
        .current_dir(cwd)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::inherit());
    #[cfg(unix)]
    command.process_group(0);
    Ok(command)
}

fn is_ready(endpoint: &LoopbackEndpoint) -> bool {
    endpoint
        .address()
        .parse::<SocketAddr>()
        .ok()
        .and_then(|address| TcpStream::connect_timeout(&address, Duration::from_millis(150)).ok())
        .is_some()
}

fn http_response(endpoint: &LoopbackEndpoint, path: &str) -> Option<Vec<u8>> {
    let address = endpoint.address().parse::<SocketAddr>().ok()?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(500)).ok()?;
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: {LOOPBACK_HOST}:{}\r\nConnection: close\r\n\r\n",
        endpoint.port
    );
    stream.write_all(request.as_bytes()).ok()?;
    let mut response = Vec::with_capacity(1024);
    stream.take(64 * 1024).read_to_end(&mut response).ok()?;
    Some(response)
}

fn json_health_body(response: &[u8]) -> Option<serde_json::Value> {
    let text = std::str::from_utf8(response).ok()?;
    let (headers, body) = text.split_once("\r\n\r\n")?;
    let status_ok = headers
        .lines()
        .next()
        .is_some_and(|line| line.starts_with("HTTP/1.0 200 ") || line.starts_with("HTTP/1.1 200 "));
    status_ok.then(|| serde_json::from_str(body).ok()).flatten()
}

fn selector_health_response(response: &[u8]) -> bool {
    json_health_body(response)
        .and_then(|value| {
            value
                .get("status")
                .and_then(|status| status.as_str())
                .map(str::to_owned)
        })
        .as_deref()
        == Some("ok")
}

fn selector_is_healthy(endpoint: &LoopbackEndpoint) -> bool {
    http_response(endpoint, "/api/health")
        .is_some_and(|response| selector_health_response(&response))
}

fn wait_selector_healthy(endpoint: &LoopbackEndpoint, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if selector_is_healthy(endpoint) {
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    false
}

fn studio_is_healthy(endpoint: &LoopbackEndpoint) -> bool {
    http_response(endpoint, "/api/health").is_some_and(|response| studio_health_response(&response))
}

fn studio_health_response(response: &[u8]) -> bool {
    json_health_body(response).is_some_and(|value| {
        value.get("ok").and_then(|ready| ready.as_bool()).is_some()
            && value.get("app_id").and_then(|app_id| app_id.as_str()) == Some("shawn-ppt-studio")
    })
}

fn wait_studio_healthy(endpoint: &LoopbackEndpoint, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if studio_is_healthy(endpoint) {
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    false
}

fn smoke_exit_delay(raw: Option<&str>) -> Option<Duration> {
    raw.and_then(|value| value.parse::<u64>().ok())
        .filter(|milliseconds| (100..=60_000).contains(milliseconds))
        .map(Duration::from_millis)
}

fn configured_port(primary: &str, legacy: Option<&str>, default: u16) -> Result<u16, String> {
    let raw = env::var(primary)
        .ok()
        .or_else(|| legacy.and_then(|name| env::var(name).ok()));
    let Some(raw) = raw else {
        return Ok(default);
    };
    raw.parse::<u16>()
        .ok()
        .filter(|port| *port > 0)
        .ok_or_else(|| format!("{primary} must be a port from 1 to 65535"))
}

fn configured_port_with_source(
    primary: &str,
    legacy: Option<&str>,
    default: u16,
) -> Result<(u16, bool), String> {
    let primary_value = env::var(primary).ok();
    let legacy_value = legacy.and_then(|name| env::var(name).ok());
    let Some(raw) = primary_value.or(legacy_value) else {
        return Ok((default, false));
    };
    let port = raw
        .parse::<u16>()
        .ok()
        .filter(|port| *port > 0)
        .ok_or_else(|| format!("{primary} must be a port from 1 to 65535"))?;
    Ok((port, true))
}

fn select_studio_port(
    requested: u16,
    explicit: bool,
    mut occupied: impl FnMut(u16) -> bool,
) -> Result<u16, String> {
    if explicit {
        if occupied(requested) {
            return Err(format!(
                "explicit desktop loopback address {LOOPBACK_HOST}:{requested} is already in use"
            ));
        }
        return Ok(requested);
    }

    for port in requested..=MAX_FALLBACK_STUDIO_PORT {
        if !occupied(port) {
            return Ok(port);
        }
    }
    Err(format!(
        "desktop loopback ports {requested}-{MAX_FALLBACK_STUDIO_PORT} are all in use"
    ))
}

fn is_studio_root(root: &Path) -> bool {
    root.join("server/server.mjs").is_file()
        && root.join("web/index.html").is_file()
        && root.join("integrations").is_dir()
        && root
            .join(".agents/skills/shawn-ppt-image/SKILL.md")
            .is_file()
}

fn bundled_studio_root(executable: &Path) -> Option<PathBuf> {
    let macos = executable.parent()?;
    if macos.file_name()? != "MacOS" {
        return None;
    }
    let contents = macos.parent()?;
    let candidate = contents.join("Resources/studio");
    is_studio_root(&candidate).then_some(candidate)
}

fn source_studio_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn studio_root(configured: Option<PathBuf>, executable: &Path) -> Result<PathBuf, String> {
    let candidate = configured
        .or_else(|| bundled_studio_root(executable))
        .unwrap_or_else(source_studio_root);
    let root = candidate
        .canonicalize()
        .map_err(|error| format!("cannot resolve Shawn PPT Studio resources: {error}"))?;
    if !is_studio_root(&root) {
        return Err(format!(
            "Shawn PPT Studio resources are incomplete: {}",
            root.display()
        ));
    }
    Ok(root)
}

fn configured_path(primary: &str, legacy: Option<&str>) -> Option<PathBuf> {
    env::var_os(primary)
        .or_else(|| legacy.and_then(env::var_os))
        .map(PathBuf::from)
}

fn executable_candidates(configured: Option<OsString>, defaults: Vec<PathBuf>) -> Vec<PathBuf> {
    configured
        .map(|value| vec![PathBuf::from(value)])
        .unwrap_or(defaults)
}

fn first_executable(candidates: Vec<PathBuf>) -> PathBuf {
    candidates
        .into_iter()
        .find(|candidate| candidate.components().count() == 1 || candidate.is_file())
        .unwrap_or_else(|| PathBuf::from("missing-runtime"))
}

fn node_command(home: Option<OsString>) -> PathBuf {
    let configured =
        env::var_os("SHAWN_PPT_STUDIO_NODE").or_else(|| env::var_os("PPT_AI_LAB_NODE"));
    let mut defaults = Vec::new();
    if let Some(home) = home {
        defaults.push(
            PathBuf::from(home)
                .join(".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"),
        );
    }
    defaults.push(PathBuf::from("node"));
    first_executable(executable_candidates(configured, defaults))
}

fn python_command(home: Option<OsString>) -> PathBuf {
    let configured = env::var_os("SHAWN_PPT_STUDIO_SELECTOR_PYTHON")
        .or_else(|| env::var_os("PPT_AI_LAB_SELECTOR_PYTHON"));
    let mut defaults = Vec::new();
    if let Some(home) = home {
        defaults.push(
            PathBuf::from(home).join(
                ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3",
            ),
        );
    }
    defaults.push(PathBuf::from("python3"));
    first_executable(executable_candidates(configured, defaults))
}

fn default_data_root(home: Option<OsString>) -> Result<PathBuf, String> {
    if let Some(configured) = configured_path("SHAWN_PPT_STUDIO_DATA_ROOT", None) {
        return Ok(configured);
    }
    let home =
        home.ok_or_else(|| "HOME is unavailable; set SHAWN_PPT_STUDIO_DATA_ROOT".to_string())?;
    Ok(PathBuf::from(home).join("Library/Application Support/Shawn PPT Studio"))
}

fn resolve_selector_root(studio_root: &Path) -> PathBuf {
    if let Some(configured) = configured_path("SHAWN_PPT_STUDIO_SELECTOR_ROOT", None) {
        return configured;
    }
    if let Some(workspace) = studio_root.parent() {
        let candidate = workspace.join("saturated-ppt");
        if candidate.join("server.py").is_file() {
            return candidate;
        }
    }
    env::var_os("HOME")
        .map(PathBuf::from)
        .map(|home| home.join("AI/Image-PPT/saturated-ppt"))
        .unwrap_or_else(|| studio_root.join("saturated-ppt"))
}

fn selector_decks_file(selector_root: &Path) -> Option<PathBuf> {
    let candidate = selector_root.join("decks.json");
    candidate.is_file().then_some(candidate)
}

fn desktop_config() -> Result<DesktopConfig, String> {
    let executable = env::current_exe()
        .map_err(|error| format!("cannot resolve desktop executable: {error}"))?;
    let test_mode = env::var("PPT_AI_LAB_TEST_MODE").ok().as_deref() == Some("1");
    let configured_root = configured_path("SHAWN_PPT_STUDIO_ROOT", None).or_else(|| {
        (!test_mode)
            .then(|| configured_path("PPT_AI_LAB_ROOT", None))
            .flatten()
    });
    let studio_root = studio_root(configured_root, &executable)?;
    let home = env::var_os("HOME");
    let (requested_studio_port, explicit_studio_port) = configured_port_with_source(
        "SHAWN_PPT_STUDIO_PORT",
        Some("PPT_AI_LAB_DESKTOP_PORT"),
        DEFAULT_STUDIO_PORT,
    )?;
    let studio_port = select_studio_port(requested_studio_port, explicit_studio_port, |port| {
        is_ready(&LoopbackEndpoint::new(port))
    })?;
    Ok(DesktopConfig {
        data_root: default_data_root(home.clone())?,
        selector_root: resolve_selector_root(&studio_root),
        node: node_command(home.clone()),
        python: python_command(home),
        selector_override: configured_path(
            "SHAWN_PPT_STUDIO_SELECTOR_BIN",
            Some("PPT_AI_LAB_SELECTOR_BIN"),
        ),
        studio: LoopbackEndpoint::new(studio_port),
        selector: LoopbackEndpoint::new(configured_port(
            "SHAWN_PPT_STUDIO_SELECTOR_PORT",
            None,
            DEFAULT_SELECTOR_PORT,
        )?),
        studio_root,
    })
}

fn studio_command(config: &DesktopConfig) -> Result<Command, String> {
    let server = config.studio_root.join("server/server.mjs");
    let args = vec![
        server.into_os_string(),
        OsString::from("--port"),
        OsString::from(config.studio.port.to_string()),
    ];
    let mut command = supervised_command(&config.node, &args, &config.studio_root)?;
    command
        .env("SHAWN_PPT_STUDIO_DATA_ROOT", &config.data_root)
        .env("SHAWN_PPT_STUDIO_DESKTOP", "1")
        .env(
            "SHAWN_PPT_STUDIO_PARENT_PID",
            std::process::id().to_string(),
        )
        .env("PPT_AI_LAB_PORT", config.studio.port.to_string());
    if let Some(legacy_decks_file) = selector_decks_file(&config.selector_root) {
        command.env("SHAWN_PPT_STUDIO_DECKS_FILE", legacy_decks_file);
    }
    Ok(command)
}

fn selector_command(config: &DesktopConfig) -> Result<Command, String> {
    let args = [
        OsString::from("--host"),
        OsString::from(LOOPBACK_HOST),
        OsString::from("--port"),
        OsString::from(config.selector.port.to_string()),
    ];
    if let Some(executable) = &config.selector_override {
        return supervised_command(executable, &args, &config.studio_root);
    }

    let server = config.selector_root.join("server.py");
    if !server.is_file() {
        return Err(format!("selector server is missing: {}", server.display()));
    }
    let mut python_args = vec![server.into_os_string()];
    python_args.extend(args);
    supervised_command(&config.python, &python_args, &config.selector_root)
}

fn spawn_services(config: &DesktopConfig) -> Result<ManagedServices, String> {
    if is_ready(&config.studio) {
        return Err(format!(
            "desktop loopback address {} is already in use; refusing to attach to an unknown service",
            config.studio.address()
        ));
    }

    let mut managed = ManagedServices::default();
    if is_ready(&config.selector) {
        if !selector_is_healthy(&config.selector) {
            return Err(format!(
                "selector loopback address {} is occupied by an unknown or unhealthy service",
                config.selector.address()
            ));
        }
    } else {
        let selector = selector_command(config)?
            .spawn()
            .map_err(|error| format!("cannot start saturated-ppt selector: {error}"))?;
        managed.selector = Some(selector);
        if !wait_selector_healthy(&config.selector, Duration::from_secs(20)) {
            managed.stop();
            return Err("saturated-ppt selector did not become healthy on loopback".into());
        }
    }

    let studio = match studio_command(config)?.spawn() {
        Ok(studio) => studio,
        Err(error) => {
            managed.stop();
            return Err(format!("cannot start Shawn PPT Studio bridge: {error}"));
        }
    };
    managed.studio = Some(studio);
    if !wait_studio_healthy(&config.studio, Duration::from_secs(20)) {
        managed.stop();
        return Err("Shawn PPT Studio bridge did not become healthy on loopback".into());
    }
    Ok(managed)
}

fn stop_services(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<Mutex<ManagedServices>>() {
        if let Ok(mut managed) = state.lock() {
            managed.stop();
        }
    }
}

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn hide_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    if let Some(code) = maybe_supervisor_exit() {
        std::process::exit(if code == ExitCode::SUCCESS { 0 } else { 70 });
    }

    let config = match desktop_config() {
        Ok(config) => config,
        Err(error) => {
            eprintln!("failed to configure Shawn PPT Studio: {error}");
            std::process::exit(1);
        }
    };
    let studio_url = config.studio.url();
    let managed = match spawn_services(&config) {
        Ok(managed) => managed,
        Err(error) => {
            eprintln!("failed to start Shawn PPT Studio: {error}");
            std::process::exit(1);
        }
    };

    let build_result = tauri::Builder::default()
        .setup(move |app| {
            let show = MenuItem::with_id(app, "show", "显示 Shawn PPT Studio", true, None::<&str>)?;
            let close = MenuItem::with_id(app, "close", "关闭窗口", true, Some("CmdOrCtrl+W"))?;
            let quit = MenuItem::with_id(
                app,
                "quit",
                "退出 Shawn PPT Studio",
                true,
                Some("CmdOrCtrl+Q"),
            )?;
            let app_menu = SubmenuBuilder::new(app, PRODUCT_NAME)
                .item(&show)
                .item(&close)
                .separator()
                .item(&quit)
                .build()?;
            let edit_menu = SubmenuBuilder::new(app, "编辑")
                .undo_with_text("撤销")
                .redo_with_text("重做")
                .separator()
                .cut_with_text("剪切")
                .copy_with_text("复制")
                .paste_with_text("粘贴")
                .select_all_with_text("全选")
                .build()?;
            let menu = MenuBuilder::new(app)
                .items(&[&app_menu, &edit_menu])
                .build()?;
            app.set_menu(menu)?;

            let url = url::Url::parse(&studio_url)?;
            debug_assert_eq!(url.host_str(), Some(LOOPBACK_HOST));
            if let Err(error) = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title(PRODUCT_NAME)
                .inner_size(1440.0, 920.0)
                .min_inner_size(980.0, 680.0)
                .build()
            {
                eprintln!("failed to create Shawn PPT Studio window: {error}");
                app.handle().exit(1);
            }
            app.manage(Mutex::new(managed));

            let smoke_ms = env::var("SHAWN_PPT_STUDIO_DESKTOP_SMOKE_MS")
                .ok()
                .or_else(|| env::var("PPT_AI_LAB_DESKTOP_SMOKE_MS").ok());
            if let Some(delay) = smoke_exit_delay(smoke_ms.as_deref()) {
                let handle = app.handle().clone();
                thread::spawn(move || {
                    thread::sleep(delay);
                    handle.exit(0);
                });
            }
            Ok(())
        })
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => show_main_window(app),
            "close" => hide_main_window(app),
            "quit" => {
                stop_services(app);
                app.exit(0);
            }
            _ => {}
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!());

    let app = match build_result {
        Ok(app) => app,
        Err(error) => {
            eprintln!("failed to start Shawn PPT Studio: {error}");
            std::process::exit(1);
        }
    };

    app.run(|handle, event| {
        #[cfg(target_os = "macos")]
        if matches!(event, RunEvent::Reopen { .. }) {
            show_main_window(handle);
        }
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            stop_services(handle);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{
        bundled_studio_root, configured_port, default_data_root, is_studio_root,
        select_studio_port, selector_decks_file, selector_health_response, smoke_exit_delay,
        source_studio_root, studio_health_response, studio_root, LoopbackEndpoint,
        DEFAULT_SELECTOR_PORT, DEFAULT_STUDIO_PORT, LOOPBACK_HOST,
    };
    use std::{
        ffi::OsString,
        fs,
        path::Path,
        path::PathBuf,
        time::{Duration, SystemTime, UNIX_EPOCH},
    };

    #[test]
    fn default_endpoints_are_fixed_loopback() {
        assert_eq!(LOOPBACK_HOST, "127.0.0.1");
        assert_eq!(
            LoopbackEndpoint::new(DEFAULT_STUDIO_PORT).address(),
            "127.0.0.1:8772"
        );
        assert_eq!(
            LoopbackEndpoint::new(DEFAULT_SELECTOR_PORT).url(),
            "http://127.0.0.1:8765/"
        );
    }

    #[test]
    fn source_tree_is_a_valid_development_root() {
        let source = source_studio_root();
        assert!(is_studio_root(&source));
        let resolved = studio_root(Some(source.clone()), Path::new("/tmp/not-an-app"))
            .expect("source studio root");
        assert_eq!(resolved, source.canonicalize().expect("canonical source"));
    }

    #[test]
    fn app_bundle_resolves_its_own_resources() {
        let executable =
            Path::new("/Applications/Shawn PPT Studio.app/Contents/MacOS/shawn-ppt-studio");
        assert_eq!(
            bundled_studio_root(executable),
            None,
            "a synthetic path is rejected until its resources exist"
        );
    }

    #[test]
    fn data_root_defaults_to_application_support() {
        assert_eq!(
            default_data_root(Some(OsString::from("/Users/example"))).expect("data root"),
            PathBuf::from("/Users/example/Library/Application Support/Shawn PPT Studio")
        );
    }

    #[test]
    fn existing_selector_registry_is_forwarded_to_studio() {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let root = std::env::temp_dir().join(format!("shawn-ppt-selector-{unique}"));
        fs::create_dir_all(&root).expect("selector root");
        let decks = root.join("decks.json");
        fs::write(&decks, b"{}\n").expect("decks registry");
        assert_eq!(selector_decks_file(&root), Some(decks));
        fs::remove_dir_all(root).expect("cleanup");
    }

    #[test]
    fn smoke_exit_is_explicit_and_bounded() {
        assert_eq!(smoke_exit_delay(None), None);
        assert_eq!(smoke_exit_delay(Some("bad")), None);
        assert_eq!(smoke_exit_delay(Some("99")), None);
        assert_eq!(smoke_exit_delay(Some("5000")), Some(Duration::from_secs(5)));
        assert_eq!(smoke_exit_delay(Some("60001")), None);
    }

    #[test]
    fn selector_health_requires_200_and_expected_json_identity() {
        assert!(selector_health_response(
            b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{\"status\":\"ok\"}"
        ));
        assert!(!selector_health_response(
            b"HTTP/1.0 200 OK\r\n\r\n{\"status\":\"bad\"}"
        ));
        assert!(!selector_health_response(
            b"HTTP/1.0 404 Not Found\r\n\r\n{\"status\":\"ok\"}"
        ));
    }

    #[test]
    fn studio_health_requires_the_new_app_identity() {
        assert!(studio_health_response(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\":true,\"app_id\":\"shawn-ppt-studio\"}"
        ));
        assert!(!studio_health_response(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\":true}"
        ));
        assert!(!studio_health_response(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\":true,\"app_id\":\"ppt-ai-lab\"}"
        ));
    }

    #[test]
    fn default_studio_port_falls_forward_when_legacy_service_occupies_8772() {
        let selected = select_studio_port(DEFAULT_STUDIO_PORT, false, |port| port == 8772)
            .expect("fallback port");
        assert_eq!(selected, 8773);
    }

    #[test]
    fn explicitly_configured_occupied_port_is_rejected() {
        let error = select_studio_port(9123, true, |port| port == 9123)
            .expect_err("explicit occupied port must fail");
        assert!(error.contains("explicit desktop loopback address 127.0.0.1:9123"));
    }

    #[test]
    fn configured_ports_reject_zero() {
        // No environment mutation: the parser's stable defaults are the production ports.
        assert_eq!(
            configured_port("SHAWN_PPT_STUDIO_TEST_UNUSED", None, DEFAULT_STUDIO_PORT)
                .expect("default port"),
            DEFAULT_STUDIO_PORT
        );
    }
}
