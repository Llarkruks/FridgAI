import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  ArrowRight,
  BarChart3,
  Camera,
  Check,
  ChefHat,
  Clock3,
  Heart,
  LogOut,
  LockKeyhole,
  Minus,
  Play,
  Plus,
  Refrigerator,
  RotateCcw,
  Search,
  Sparkles,
  Square,
  Trash2,
  UploadCloud,
  UserRound,
  Video,
  X,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const API_URL = "http://127.0.0.1:8000";

const YOLOV8_BASELINE = {
  model: "yolov8n",
  classes: 31,
  epochs_configured: 35,
  mAP50: 0.7639,
  mAP50_95: 0.5439,
  precision: 0.7567,
  recall: 0.7184,
  f1_approx: 0.7371,
  speed_ms: { inference: 4.36 },
};

const Icon = ({ name, size = 20 }) => {
  const icons = {
    scan: Camera,
    fridge: Refrigerator,
    recipes: ChefHat,
    dashboard: BarChart3,
    search: Search,
    user: UserRound,
    lock: LockKeyhole,
    camera: Camera,
    upload: UploadCloud,
    plus: Plus,
    trash: Trash2,
    heart: Heart,
    logout: LogOut,
    check: Check,
    alert: AlertCircle,
    minus: Minus,
    clock: Clock3,
    arrow: ArrowRight,
  };
  const IconComponent = icons[name] || AlertCircle;
  return <IconComponent className={`icon icon-${name}`} size={size} strokeWidth={1.8} aria-hidden="true" />;
};

async function apiRequest(path, token, options = {}) {
  const headers = new Headers(options.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!response.ok) throw new Error(data?.detail || "No se pudo completar la solicitud.");
  return data;
}

function splitInstructions(instructions) {
  if (!instructions) return [];
  const text = String(instructions).replace(/\r/g, "").trim();
  const separated = text
    .replace(/([.!?])(\d+[-.)]\s+)/g, "$1\n$2")
    .replace(/\s+(\d+[-.)]\s+)/g, "\n$1")
    .replace(/(^|\n)\s*\d+[-.)]\s*/g, "$1")
    .split(/\n+/)
    .map((step) => step.trim())
    .filter(Boolean);
  if (separated.length > 1) {
    return separated;
  }

  const sentences = text
    .split(/(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿])/)
    .map((step) => step.trim())
    .filter(Boolean);
  return sentences.length > 1 ? sentences : [text];
}

function ingredientIcon(name) {
  const normalized = String(name).toLowerCase();
  const icons = [
    [["manzana", "pera", "plátano", "banana", "naranja", "limón", "fruta"], "◒"],
    [["tomate", "lechuga", "espinaca", "cebolla", "ajo", "zanahoria", "verdura"], "⌑"],
    [["leche", "queso", "yogur", "lácteo"], "◌"],
    [["huevo", "pollo", "pescado", "carne", "ternera", "jamón"], "◇"],
    [["arroz", "pan", "pasta", "cereal", "harina"], "◫"],
  ];
  return icons.find(([keys]) => keys.some((key) => normalized.includes(key)))?.[1] || "•";
}

function DetectionOverlay({ detections, frameSize, confirmedList = [], liveMode = false }) {
  if (!detections.length || !frameSize.width || !frameSize.height) return null;
  const fontSize = Math.max(12, Math.round(frameSize.width * 0.026));
  const labelHeight = Math.round(fontSize * 1.55);
  const padX = Math.round(fontSize * 0.5);

  return (
    <svg
      className="bbox-overlay"
      viewBox={`0 0 ${frameSize.width} ${frameSize.height}`}
      preserveAspectRatio="xMidYMid meet"
      aria-label="Ingredientes detectados"
    >
      {detections.map((item, index) => {
        const [x1, y1, x2, y2] = item.bbox;
        const width = Math.max(0, x2 - x1);
        const height = Math.max(0, y2 - y1);
        const isConfirmed = confirmedList.includes(item.ingredient_es);
        const prefix = isConfirmed ? "✓ " : "";
        const text = `${prefix}${item.ingredient_es} · ${Math.round(item.confidence * 100)}%`;
        const approxW = Math.max(labelHeight * 3, text.length * fontSize * 0.58 + padX * 2);
        const labelY = Math.max(0, y1 - labelHeight);
        const stateClass = isConfirmed ? "confirmed" : liveMode ? "live" : "static";

        return (
          <g key={`${item.ingredient_es}-${index}`}>
            <rect x={x1} y={y1} width={width} height={height} rx={4} className={`bbox-box ${stateClass}`} />
            <rect x={x1} y={labelY} width={approxW} height={labelHeight} rx={4} className={`bbox-label-bg ${stateClass}`} />
            <text
              x={x1 + padX}
              y={labelY + labelHeight * 0.72}
              style={{ fontSize: `${fontSize}px` }}
              className={`bbox-label ${stateClass}`}
            >
              {text}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem("fridgia_token"));
  const [username, setUsername] = useState(() => localStorage.getItem("fridgia_username"));
  const [page, setPage] = useState("scan");
  const [health, setHealth] = useState(null);
  const [authMode, setAuthMode] = useState("login");
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [toast, setToast] = useState(null);

  const notify = (message, type = "success") => {
    setToast({ message, type, id: Date.now() });
    window.clearTimeout(window.__fridgiaToast);
    window.__fridgiaToast = window.setTimeout(() => setToast(null), 3200);
  };

  useEffect(() => {
    apiRequest("/health").then(setHealth).catch(() => setHealth(null));
  }, []);

  const login = async (event) => {
    event.preventDefault();
    setAuthLoading(true);
    setAuthError("");
    const form = new FormData(event.currentTarget);
    try {
      if (authMode === "register") {
        await apiRequest("/register", null, {
          method: "POST",
          body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
        });
        setAuthMode("login");
        setAuthError("Cuenta creada. Ya puedes iniciar sesión.");
      } else {
        const body = new URLSearchParams({
          username: form.get("username"),
          password: form.get("password"),
        });
        const data = await apiRequest("/token", null, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body,
        });
        localStorage.setItem("fridgia_token", data.access_token);
        localStorage.setItem("fridgia_username", form.get("username"));
        setToken(data.access_token);
        setUsername(form.get("username"));
      }
    } catch (error) {
      setAuthError(error.message);
    } finally {
      setAuthLoading(false);
    }
  };

  const logout = () => {
    localStorage.removeItem("fridgia_token");
    localStorage.removeItem("fridgia_username");
    setToken(null);
    setUsername(null);
  };

  const nav = [
    ["scan", "Escáner", Camera],
    ["fridge", "Mi nevera", Refrigerator],
    ["recipes", "Recetas", ChefHat],
    ["dashboard", "Analítica", BarChart3],
  ];

  return (
    !token ? (
      <AuthScreen authMode={authMode} setAuthMode={setAuthMode} onSubmit={login} error={authError} loading={authLoading} health={health} />
    ) : (
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-mark">F</div>
            <div>
              <strong>FridgIA</strong>
              <span>Smart kitchen</span>
            </div>
          </div>

          <nav className="nav-list" aria-label="Navegación principal">
            {nav.map(([id, label, Glyph]) => (
              <button key={id} className={page === id ? "nav-item active" : "nav-item"} onClick={() => setPage(id)}>
                <span className="nav-glyph"><Glyph size={17} strokeWidth={1.9} /></span>
                <span>{label}</span>
              </button>
            ))}
          </nav>

          <div className="sidebar-footer">
            <div className="profile-row">
              <div className="avatar">{username?.[0]?.toUpperCase() || "U"}</div>
              <div className="profile-copy">
                <strong>{username}</strong>
                <span>{health ? `${health.visual_classes} clases · YOLO11s` : "Mi espacio"}</span>
              </div>
              <button className="icon-button" onClick={logout} title="Cerrar sesión"><Icon name="logout" /></button>
            </div>
          </div>
        </aside>

        <main className="main-content">
          <AnimatePresence mode="wait">
            {page === "scan" && (
              <motion.div key="scan" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }} transition={{ duration: 0.22 }}>
                <Scanner token={token} notify={notify} />
              </motion.div>
            )}
            {page === "fridge" && (
              <motion.div key="fridge" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }} transition={{ duration: 0.22 }}>
                <Fridge token={token} notify={notify} />
              </motion.div>
            )}
            {page === "recipes" && (
              <motion.div key="recipes" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }} transition={{ duration: 0.22 }}>
                <Recipes token={token} notify={notify} />
              </motion.div>
            )}
          </AnimatePresence>
          {page === "dashboard" && <Dashboard token={token} />}
        </main>

        <AnimatePresence>
          {toast && (
            <motion.div
              className={`toast toast-${toast.type}`}
              role="status"
              aria-live="polite"
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.98 }}
            >
              {toast.type === "success" ? <Check size={17} /> : <AlertCircle size={17} />}
              <span>{toast.message}</span>
              <button onClick={() => setToast(null)} aria-label="Cerrar notificación"><X size={14} /></button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    )
  );
}

function AuthScreen({ authMode, setAuthMode, onSubmit, error, loading, health }) {
  return (
    <div className="auth-page">
      <section className="auth-visual">
        <div className="visual-grid" />
        <div className="visual-content">
          <div className="eyebrow light">Tu cocina, más inteligente</div>
          <h1>Convierte lo que tienes en una comida extraordinaria.</h1>
          <p>Reconoce ingredientes en vivo, controla tu nevera y encuentra recetas que aprovechan lo que ya tienes.</p>
          <div className="feature-stack">
            <div><span>01</span><b>Escanea</b><small>Visión con YOLO11s</small></div>
            <div><span>02</span><b>Organiza</b><small>Inventario personal</small></div>
            <div><span>03</span><b>Cocina</b><small>Recetas recomendadas</small></div>
          </div>
        </div>
        <div className="visual-badge">
          <span className={health ? "status-dot online" : "status-dot"} />
          <b>{health ? "Sistema operativo" : "Conectando"}</b>
          <small>{health ? `${health.visual_classes} clases visuales` : "FastAPI"}</small>
        </div>
      </section>

      <section className="auth-card-wrap">
        <div className="auth-card">
          <div className="auth-mobile-brand"><div className="brand-mark">F</div><strong>FridgIA</strong></div>
          <div className="eyebrow">{authMode === "login" ? "Bienvenido de nuevo" : "Crea tu cuenta"}</div>
          <h2>{authMode === "login" ? "Inicia sesión" : "Registro"}</h2>
          <p className="auth-subtitle">
            {authMode === "login" ? "Accede a tu nevera inteligente." : "Empieza a organizar tu cocina."}
          </p>

          <div className="auth-tabs">
            <button className={authMode === "login" ? "active" : ""} onClick={() => setAuthMode("login")}>Entrar</button>
            <button className={authMode === "register" ? "active" : ""} onClick={() => setAuthMode("register")}>Crear cuenta</button>
          </div>

          <form onSubmit={onSubmit} className="auth-form">
            <label><span>Usuario</span><div className="input-wrap"><Icon name="user" /><input name="username" defaultValue={authMode === "login" ? "demo" : ""} minLength={3} required placeholder="Tu usuario" /></div></label>
            <label><span>Contraseña</span><div className="input-wrap"><Icon name="lock" /><input name="password" type="password" defaultValue={authMode === "login" ? "demo1234" : ""} minLength={6} required placeholder="••••••••" /></div></label>
            {error && <div className={error.includes("creada") ? "form-message success" : "form-message"}>{error.includes("creada") ? <Icon name="check" /> : <Icon name="alert" />}{error}</div>}
            {authMode === "login" && <div className="demo-note"><span>Acceso de demostración</span><b>demo · demo1234</b></div>}
            <button className="primary-button" type="submit" disabled={loading}>{loading ? "Procesando..." : authMode === "login" ? "Entrar a mi nevera" : "Crear cuenta"}<span>→</span></button>
          </form>

          <div className="auth-health"><span className={health ? "status-dot online" : "status-dot"} /><span>{health ? "Conexión segura con FastAPI" : "Esperando al servidor"}</span></div>
        </div>
      </section>
    </div>
  );
}

function PageHeader({ eyebrow, title, description, action }) {
  return (
    <header className="page-header">
      <div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>
      {action}
    </header>
  );
}

function Scanner({ token, notify }) {
  // Modo activo: "live" | "upload" | "camera"
  const [source, setSource] = useState("live");

  // Estados de foto única / subir foto
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState("");
  const [confidence, setConfidence] = useState(0.30);
  const [enhance, setEnhance] = useState(false);
  const [tta, setTta] = useState(false);
  const [detections, setDetections] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [inference, setInference] = useState(null);
  const [selectedDetections, setSelectedDetections] = useState([]);
  const [previewSize, setPreviewSize] = useState({ width: 1, height: 1 });

  // Estados de cámara compartida (Live y Foto única)
  const [cameraActive, setCameraActive] = useState(false);
  const [cameraStarting, setCameraStarting] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const [cameraReady, setCameraReady] = useState(false);

  // Estados específicos de modo Live (60 FPS vídeo + inferencia asíncrona)
  const [liveConf, setLiveConf] = useState(0.20);
  const [liveEnhance, setLiveEnhance] = useState(true);
  const [liveFast, setLiveFast] = useState(true);
  const [liveDetections, setLiveDetections] = useState([]);
  const [liveFrameSize, setLiveFrameSize] = useState({ width: 640, height: 480 });
  const [liveInference, setLiveInference] = useState(null);
  const [liveSeen, setLiveSeen] = useState({});
  const [liveDiscarded, setLiveDiscarded] = useState([]);
  const [liveConfirmed, setLiveConfirmed] = useState([]);

  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const captureCanvasRef = useRef(null);
  const liveRunningRef = useRef(false);
  const liveTimerRef = useRef(null);
  const liveAbortRef = useRef(null);

  // Refs sincronizados para que el bucle Live lea cambios al vuelo sin reiniciar la cámara
  const liveConfRef = useRef(liveConf);
  const liveEnhanceRef = useRef(liveEnhance);
  const liveFastRef = useRef(liveFast);
  const discardedRef = useRef(new Set());
  const confirmedRef = useRef(new Set());

  useEffect(() => { liveConfRef.current = liveConf; }, [liveConf]);
  useEffect(() => { liveEnhanceRef.current = liveEnhance; }, [liveEnhance]);
  useEffect(() => { liveFastRef.current = liveFast; }, [liveFast]);
  useEffect(() => { discardedRef.current = new Set(liveDiscarded); }, [liveDiscarded]);
  useEffect(() => { confirmedRef.current = new Set(liveConfirmed); }, [liveConfirmed]);

  // Limpieza al desmontar
  useEffect(() => {
    return () => {
      liveRunningRef.current = false;
      window.clearTimeout(liveTimerRef.current);
      liveAbortRef.current?.abort();
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  useEffect(() => {
    return () => {
      if (preview?.startsWith("blob:")) URL.revokeObjectURL(preview);
    };
  }, [preview]);

  // Conectar MediaStream al elemento <video> cuando la cámara está activa
  useEffect(() => {
    if (!cameraActive || !streamRef.current) return;
    const video = videoRef.current;
    if (!video) return;
    video.srcObject = streamRef.current;
    video.muted = true;
    video.playsInline = true;
    video.play().catch(() => {});
    const markReady = () => setCameraReady(true);
    video.addEventListener("loadeddata", markReady);
    video.addEventListener("canplay", markReady);
    return () => {
      video.removeEventListener("loadeddata", markReady);
      video.removeEventListener("canplay", markReady);
    };
  }, [cameraActive, source]);

  // Bucle asíncrono de inferencia en modo Live (no bloquea el renderizado nativo del <video>)
  useEffect(() => {
    if (!cameraActive || source !== "live") return;
    liveRunningRef.current = true;

    const runStep = async () => {
      if (!liveRunningRef.current) return;
      const video = videoRef.current;

      if (video && video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0) {
        const maxWidth = liveFastRef.current ? 480 : 640;
        const scale = Math.min(1, maxWidth / video.videoWidth);
        const w = Math.max(160, Math.round(video.videoWidth * scale));
        const h = Math.max(120, Math.round(video.videoHeight * scale));

        if (!captureCanvasRef.current) {
          captureCanvasRef.current = document.createElement("canvas");
        }
        const canvas = captureCanvasRef.current;
        if (canvas.width !== w || canvas.height !== h) {
          canvas.width = w;
          canvas.height = h;
        }
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, w, h);

        const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.82));
        if (blob && liveRunningRef.current) {
          const form = new FormData();
          form.append("image", blob, "live.jpg");
          const params = new URLSearchParams({
            conf: String(liveConfRef.current),
            enhance: String(liveEnhanceRef.current),
            tta: "false",
            imgsz: String(liveFastRef.current ? 480 : 640),
            log_scan: "false",
          });

          try {
            const controller = new AbortController();
            liveAbortRef.current = controller;
            const data = await apiRequest(`/recognize?${params}`, token, {
              method: "POST",
              body: form,
              signal: controller.signal,
            });
            if (!liveRunningRef.current) return;

            const rawItems = data.detected_items || [];
            setLiveFrameSize({ width: w, height: h });
            setLiveInference(data.inference_ms);
            setLiveDetections(rawItems);

            const now = Date.now();
            setLiveSeen((prev) => {
              const next = {};
              for (const [ing, info] of Object.entries(prev)) {
                if (
                  !discardedRef.current.has(ing) &&
                  (now - info.lastSeen <= 8000 || confirmedRef.current.has(ing))
                ) {
                  next[ing] = { ...info, activeNow: false };
                }
              }
              for (const item of rawItems) {
                const ing = item.ingredient_es;
                if (discardedRef.current.has(ing)) continue;
                const existing = next[ing];
                next[ing] = {
                  class_en: item.class_en,
                  lastConf: item.confidence,
                  maxConf: existing ? Math.max(existing.maxConf, item.confidence) : item.confidence,
                  lastSeen: now,
                  activeNow: true,
                };
              }
              return next;
            });
          } catch (err) {
            if (err.name !== "AbortError") {
              setError(err.message);
            }
          }
        }
      }

      if (liveRunningRef.current) {
        liveTimerRef.current = window.setTimeout(runStep, 120);
      }
    };

    runStep();

    return () => {
      liveRunningRef.current = false;
      window.clearTimeout(liveTimerRef.current);
      liveAbortRef.current?.abort();
    };
  }, [cameraActive, source, token]);

  const stopCamera = () => {
    liveRunningRef.current = false;
    window.clearTimeout(liveTimerRef.current);
    liveAbortRef.current?.abort();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setCameraActive(false);
    setCameraStarting(false);
    setCameraReady(false);
    setLiveDetections([]);
    setLiveInference(null);
  };

  const readPreviewSize = (imgUrl) => {
    const image = new Image();
    image.onload = () => setPreviewSize({ width: image.naturalWidth, height: image.naturalHeight });
    image.src = imgUrl;
  };

  const startCamera = async () => {
    setCameraError("");
    setError("");
    setCameraStarting(true);
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError("Este navegador no permite acceder a la cámara.");
      setCameraStarting(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      setCameraActive(true);
    } catch (requestError) {
      let message = "No se pudo iniciar la cámara.";
      if (requestError.name === "NotAllowedError" || requestError.name === "PermissionDeniedError") {
        message = "Permiso denegado. Activa la cámara desde el candado del navegador.";
      } else if (requestError.name === "NotFoundError" || requestError.name === "DevicesNotFoundError") {
        message = "No se encontró ninguna cámara disponible.";
      } else if (requestError.name === "NotReadableError" || requestError.name === "TrackStartError") {
        message = "La cámara está en uso por otra aplicación.";
      } else if (requestError.name === "OverconstrainedError") {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
          streamRef.current = stream;
          setCameraActive(true);
          setCameraStarting(false);
          return;
        } catch {
          message = "El navegador no pudo abrir una configuración compatible con la cámara.";
        }
      }
      setCameraError(message);
      notify(message, "error");
    } finally {
      setCameraStarting(false);
    }
  };

  const changeSource = (nextSource) => {
    if (nextSource === source) return;
    if (cameraActive) stopCamera();
    setSource(nextSource);
    setCameraError("");
    setError("");
    if (nextSource === "camera") {
      setConfidence(0.15);
      setEnhance(true);
      setTta(true);
    } else if (nextSource === "upload") {
      setConfidence(0.30);
      setEnhance(false);
      setTta(false);
    }
  };

  // Acciones en vivo: confirmar, descartar, restaurar y reiniciar
  const confirmLiveIngredient = async (ingredient) => {
    try {
      await apiRequest("/fridge/items", token, {
        method: "POST",
        body: JSON.stringify({ ingredient_es: ingredient, source: "camera", quantity: 1 }),
      });
      confirmedRef.current.add(ingredient);
      setLiveConfirmed((prev) => (prev.includes(ingredient) ? prev : [...prev, ingredient]));
      notify(`${ingredient} confirmado y añadido a tu nevera`);
    } catch (requestError) {
      notify(requestError.message, "error");
    }
  };

  const discardLiveIngredient = (ingredient) => {
    discardedRef.current.add(ingredient);
    setLiveDiscarded((prev) => (prev.includes(ingredient) ? prev : [...prev, ingredient]));
    setLiveSeen((prev) => {
      const next = { ...prev };
      delete next[ingredient];
      return next;
    });
  };

  const restoreLiveIngredient = (ingredient) => {
    discardedRef.current.delete(ingredient);
    setLiveDiscarded((prev) => prev.filter((item) => item !== ingredient));
  };

  const resetLiveSession = () => {
    discardedRef.current.clear();
    confirmedRef.current.clear();
    setLiveDiscarded([]);
    setLiveConfirmed([]);
    setLiveSeen({});
    notify("Sesión en vivo reiniciada");
  };

  // Acciones de foto única / subida
  const capturePhoto = () => {
    const video = videoRef.current;
    if (!video?.videoWidth || video.readyState < 2) {
      notify("La cámara todavía está iniciando. Espera un momento.", "error");
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const capturedFile = new File([blob], "captura-nevera.jpg", { type: "image/jpeg" });
      if (preview?.startsWith("blob:")) URL.revokeObjectURL(preview);
      setFile(capturedFile);
      const objectUrl = URL.createObjectURL(blob);
      setPreview(objectUrl);
      setPreviewSize({ width: canvas.width, height: canvas.height });
      setDetections([]);
      setSelectedDetections([]);
      setInference(null);
      stopCamera();
      notify("Foto capturada");
    }, "image/jpeg", 0.92);
  };

  const selectFile = (event) => {
    const selected = event.target.files?.[0];
    if (!selected) return;
    if (preview?.startsWith("blob:")) URL.revokeObjectURL(preview);
    setFile(selected);
    const objectUrl = URL.createObjectURL(selected);
    setPreview(objectUrl);
    readPreviewSize(objectUrl);
    setDetections([]);
    setSelectedDetections([]);
  };

  const recognize = async () => {
    if (!file) return;
    setLoading(true);
    setError("");
    const form = new FormData();
    form.append("image", file);
    const params = new URLSearchParams({
      conf: String(confidence),
      enhance: String(enhance),
      tta: String(tta),
    });
    try {
      const data = await apiRequest(`/recognize?${params}`, token, { method: "POST", body: form });
      setDetections(data.detected_items);
      setSelectedDetections([...new Set(data.detected_items.map((item) => item.ingredient_es))]);
      setInference(data.inference_ms);
    } catch (requestError) {
      setError(requestError.message);
      notify(requestError.message, "error");
    } finally {
      setLoading(false);
    }
  };

  const saveDetection = async (ingredient) => {
    try {
      await apiRequest("/fridge/items", token, {
        method: "POST",
        body: JSON.stringify({ ingredient_es: ingredient, source: "camera", quantity: 1 }),
      });
      setDetections((items) => items.map((item) => (item.ingredient_es === ingredient ? { ...item, saved: true } : item)));
      notify(`${ingredient} añadido a tu nevera`);
    } catch (requestError) {
      setError(requestError.message);
      notify(requestError.message, "error");
    }
  };

  const toggleDetection = (ingredient) => {
    setSelectedDetections((current) =>
      current.includes(ingredient)
        ? current.filter((item) => item !== ingredient)
        : [...current, ingredient],
    );
  };

  const removeDetection = (ingredient) => {
    setDetections((current) => current.filter((item) => item.ingredient_es !== ingredient));
    setSelectedDetections((current) => current.filter((item) => item !== ingredient));
  };

  const saveSelected = async () => {
    if (!selectedDetections.length) return;
    let saved = 0;
    for (const ingredient of [...new Set(selectedDetections)]) {
      try {
        await apiRequest("/fridge/items", token, {
          method: "POST",
          body: JSON.stringify({ ingredient_es: ingredient, source: "camera", quantity: 1 }),
        });
        saved += 1;
      } catch (requestError) {
        notify(requestError.message, "error");
      }
    }
    if (saved) {
      setDetections((current) =>
        current.map((item) =>
          selectedDetections.includes(item.ingredient_es) ? { ...item, saved: true } : item,
        ),
      );
      notify(`${saved} ingrediente${saved === 1 ? "" : "s"} guardado${saved === 1 ? "" : "s"} en tu nevera`);
    }
  };

  // Detecciones visibles en Live (filtradas en 0 ms al descartar)
  const visibleLiveDetections = liveDetections.filter((d) => !liveDiscarded.includes(d.ingredient_es));
  const pendingLiveEntries = Object.entries(liveSeen)
    .filter(([ing]) => !liveConfirmed.includes(ing) && !liveDiscarded.includes(ing))
    .sort(([a], [b]) => a.localeCompare(b, "es"));

  return (
    <div className="page">
      <PageHeader
        eyebrow="Visión artificial · YOLO11s"
        title="Escáner de ingredientes"
        description="Escanea en directo con tu cámara o sube una foto para añadir ingredientes a tu nevera."
      />

      <div className="scanner-layout">
        <section className="panel scanner-panel">
          <div className="panel-heading">
            <div>
              <span className="step-number">01</span>
              <h2>{source === "live" ? "Cámara en directo" : "Selecciona una imagen"}</h2>
            </div>
            <span className="format-tag">
              {source === "live"
                ? cameraActive
                  ? liveInference !== null
                    ? `LIVE · ${liveInference.toFixed(0)} ms`
                    : "LIVE · Iniciando..."
                  : "VIDEO 60 FPS"
                : "JPG · PNG · WEBP"}
            </span>
          </div>

          <div className="source-switch three-cols" role="tablist" aria-label="Modo de escaneo">
            <button type="button" role="tab" aria-selected={source === "live"} className={source === "live" ? "active" : ""} onClick={() => changeSource("live")}>
              <Video size={15} />En vivo
            </button>
            <button type="button" role="tab" aria-selected={source === "upload"} className={source === "upload" ? "active" : ""} onClick={() => changeSource("upload")}>
              <UploadCloud size={15} />Subir foto
            </button>
            <button type="button" role="tab" aria-selected={source === "camera"} className={source === "camera" ? "active" : ""} onClick={() => changeSource("camera")}>
              <Camera size={15} />Foto única
            </button>
          </div>

          {/* ==================== VISOR: MODO LIVE ==================== */}
          {source === "live" ? (
            <>
              <div className={cameraActive ? "camera-zone live-zone active" : "camera-zone live-zone"}>
                {cameraActive ? (
                  <div className="live-stage">
                    <video
                      ref={videoRef}
                      muted
                      playsInline
                      autoPlay
                      aria-label="Vídeo en directo de la cámara"
                      onLoadedMetadata={(event) => {
                        setCameraReady(true);
                        event.currentTarget.play().catch(() => {});
                      }}
                      onLoadedData={() => setCameraReady(true)}
                      onCanPlay={() => setCameraReady(true)}
                    />
                    <DetectionOverlay
                      detections={visibleLiveDetections}
                      frameSize={liveFrameSize}
                      confirmedList={liveConfirmed}
                      liveMode
                    />
                    <div className="live-pill">
                      <i />
                      <span>EN VIVO</span>
                      {liveInference !== null && <b>{liveInference.toFixed(0)} ms</b>}
                    </div>
                  </div>
                ) : (
                  <div className="camera-placeholder">
                    <div className="upload-icon"><Video size={26} /></div>
                    <strong>Escáner continuo en vivo</strong>
                    <span>Mueve los alimentos frente a la cámara para confirmar o descartar en tiempo real</span>
                  </div>
                )}
                {cameraStarting && <div className="camera-starting"><span /><strong>Abriendo cámara...</strong></div>}
                {cameraError && <div className="camera-error"><AlertCircle size={15} />{cameraError}</div>}
              </div>

              <div className="scanner-controls live-controls">
                <div className="confidence-control">
                  <div><span>Umbral de confianza</span><b>{liveConf.toFixed(2)}</b></div>
                  <input
                    type="range"
                    min="0.05"
                    max="0.85"
                    step="0.05"
                    value={liveConf}
                    onChange={(event) => setLiveConf(Number(event.target.value))}
                  />
                  <div className="inference-toggles">
                    <label className={liveEnhance ? "toggle-chip active" : "toggle-chip"}>
                      <input type="checkbox" checked={liveEnhance} onChange={(e) => setLiveEnhance(e.target.checked)} />
                      <Sparkles size={13} />CLAHE (luz)
                    </label>
                    <label className={liveFast ? "toggle-chip active" : "toggle-chip"}>
                      <input type="checkbox" checked={liveFast} onChange={(e) => setLiveFast(e.target.checked)} />
                      <Clock3 size={13} />Rápido 480px
                    </label>
                  </div>
                </div>

                {!cameraActive ? (
                  <button type="button" className="primary-button" onClick={startCamera} disabled={cameraStarting}>
                    <Play size={16} />Iniciar en vivo
                  </button>
                ) : (
                  <button type="button" className="danger-button" onClick={stopCamera}>
                    <Square size={15} />Detener cámara
                  </button>
                )}
              </div>
            </>
          ) : source === "upload" ? (
            /* ==================== VISOR: SUBIR FOTO ==================== */
            <>
              <label className={preview ? "dropzone has-preview" : "dropzone"}>
                {preview ? (
                  <div className="detection-preview">
                    <img
                      src={preview}
                      alt="Vista previa"
                      onLoad={(event) => setPreviewSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
                    />
                    <DetectionOverlay detections={detections} frameSize={previewSize} />
                  </div>
                ) : (
                  <>
                    <div className="upload-icon"><UploadCloud size={26} /></div>
                    <strong>Arrastra una imagen aquí</strong>
                    <span>o haz clic para explorar archivos</span>
                  </>
                )}
                <input type="file" accept="image/jpeg,image/png,image/webp" onChange={selectFile} />
              </label>

              <div className="scanner-controls">
                <div className="confidence-control">
                  <div><span>Umbral de confianza</span><b>{confidence.toFixed(2)}</b></div>
                  <input type="range" min="0.05" max="0.90" step="0.05" value={confidence} onChange={(event) => setConfidence(Number(event.target.value))} />
                  <div className="inference-toggles">
                    <label className={enhance ? "toggle-chip active" : "toggle-chip"}>
                      <input type="checkbox" checked={enhance} onChange={(e) => setEnhance(e.target.checked)} />
                      <Sparkles size={13} />CLAHE (luz)
                    </label>
                    <label className={tta ? "toggle-chip active" : "toggle-chip"}>
                      <input type="checkbox" checked={tta} onChange={(e) => setTta(e.target.checked)} />
                      <BarChart3 size={13} />TTA (multi-escala)
                    </label>
                  </div>
                </div>
                <button className="primary-button" onClick={recognize} disabled={!file || loading}>
                  {loading ? "Analizando..." : "Detectar ingredientes"}<span>→</span>
                </button>
              </div>
            </>
          ) : (
            /* ==================== VISOR: FOTO ÚNICA WEBCAM ==================== */
            <>
              <div className={cameraActive ? "camera-zone active" : "camera-zone"}>
                {cameraActive ? (
                  <video
                    ref={videoRef}
                    muted
                    playsInline
                    autoPlay
                    aria-label="Vista previa de la cámara"
                    onLoadedMetadata={(event) => {
                      setCameraReady(true);
                      event.currentTarget.play().catch(() => {});
                    }}
                    onLoadedData={() => setCameraReady(true)}
                    onCanPlay={() => setCameraReady(true)}
                  />
                ) : preview ? (
                  <div className="detection-preview camera-preview">
                    <img
                      src={preview}
                      alt="Foto capturada"
                      onLoad={(event) => setPreviewSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
                    />
                    <DetectionOverlay detections={detections} frameSize={previewSize} />
                  </div>
                ) : (
                  <div className="camera-placeholder">
                    <div className="upload-icon"><Camera size={26} /></div>
                    <strong>Abre tu cámara</strong>
                    <span>Captura una imagen fija para analizarla con CLAHE y TTA</span>
                  </div>
                )}
                {cameraStarting && <div className="camera-starting"><span /><strong>Solicitando acceso...</strong></div>}
                {!cameraActive && !preview && <button type="button" className="camera-action" onClick={startCamera}><Camera size={17} />Abrir cámara</button>}
                {!cameraActive && preview && <button type="button" className="camera-action" onClick={startCamera}><Camera size={17} />Nueva captura</button>}
                {cameraActive && <button type="button" className="camera-action capture" onClick={capturePhoto} disabled={!cameraReady} aria-label="Tomar foto"><span /></button>}
                {cameraError && <div className="camera-error"><AlertCircle size={15} />{cameraError}</div>}
              </div>

              <div className="scanner-controls">
                <div className="confidence-control">
                  <div><span>Umbral de confianza</span><b>{confidence.toFixed(2)}</b></div>
                  <input type="range" min="0.05" max="0.90" step="0.05" value={confidence} onChange={(event) => setConfidence(Number(event.target.value))} />
                  <div className="inference-toggles">
                    <label className={enhance ? "toggle-chip active" : "toggle-chip"}>
                      <input type="checkbox" checked={enhance} onChange={(e) => setEnhance(e.target.checked)} />
                      <Sparkles size={13} />CLAHE (luz)
                    </label>
                    <label className={tta ? "toggle-chip active" : "toggle-chip"}>
                      <input type="checkbox" checked={tta} onChange={(e) => setTta(e.target.checked)} />
                      <BarChart3 size={13} />TTA (multi-escala)
                    </label>
                  </div>
                </div>
                <button className="primary-button" onClick={recognize} disabled={!file || loading}>
                  {loading ? "Analizando..." : "Detectar ingredientes"}<span>→</span>
                </button>
              </div>
            </>
          )}
        </section>

        {/* ==================== PANEL DERECHO: RESULTADOS ==================== */}
        <section className="panel results-panel">
          {source === "live" ? (
            <>
              <div className="panel-heading">
                <div><span className="step-number">02</span><h2>Detecciones en vivo</h2></div>
                <span className="format-tag">
                  {pendingLiveEntries.length} pendientes
                </span>
              </div>

              {error && <div className="form-message"><Icon name="alert" />{error}</div>}

              {!cameraActive && !pendingLiveEntries.length && !liveConfirmed.length && !liveDiscarded.length ? (
                <div className="empty-state">
                  <div className="empty-visual"><span>◉</span></div>
                  <h3>Listo para escanear en directo</h3>
                  <p>Pulsa «Iniciar en vivo» y muestra un ingrediente. Podrás confirmar los aciertos o descartar confusiones con un clic.</p>
                </div>
              ) : (
                <div className="live-panel-body">
                  {pendingLiveEntries.length > 0 ? (
                    <>
                      <p className="detection-help">Confirma para añadir a tu nevera o descarta para ocultarlo del vídeo</p>
                      <div className="detection-list detection-cards live-cards">
                        <AnimatePresence initial={false}>
                          {pendingLiveEntries.map(([ingredient, info]) => (
                            <motion.div
                              className={info.activeNow ? "detection-card selected live-card" : "detection-card live-card stale"}
                              key={ingredient}
                              layout
                              initial={{ opacity: 0, y: 8 }}
                              animate={{ opacity: 1, y: 0 }}
                              exit={{ opacity: 0, x: 16 }}
                            >
                              <div className="live-card-top">
                                <div className="detection-name">
                                  <span className={info.activeNow ? "live-avatar active" : "live-avatar"}>
                                    {ingredient[0]?.toUpperCase()}
                                  </span>
                                  <div>
                                    <strong>{ingredient}</strong>
                                    <small>
                                      {info.activeNow ? "Visible ahora" : "Reciente"} · {info.class_en}
                                    </small>
                                  </div>
                                </div>
                                <div className="confidence">
                                  <b>{Math.round(info.lastConf * 100)}%</b>
                                  <div><span style={{ width: `${info.lastConf * 100}%` }} /></div>
                                </div>
                              </div>
                              <div className="detection-card-actions">
                                <button
                                  type="button"
                                  className="detection-save"
                                  onClick={() => confirmLiveIngredient(ingredient)}
                                >
                                  <Check size={14} />Confirmar
                                </button>
                                <button
                                  type="button"
                                  className="detection-remove"
                                  onClick={() => discardLiveIngredient(ingredient)}
                                >
                                  <X size={14} />Descartar
                                </button>
                              </div>
                            </motion.div>
                          ))}
                        </AnimatePresence>
                      </div>
                    </>
                  ) : (
                    <div className="live-waiting-box">
                      <Video size={20} />
                      <span>{cameraActive ? "Mueve un alimento frente a la cámara..." : "Cámara detenida."}</span>
                    </div>
                  )}

                  {liveConfirmed.length > 0 && (
                    <div className="live-chip-group">
                      <span className="live-group-label">Confirmados en Mi nevera ({liveConfirmed.length})</span>
                      <div className="live-chips">
                        {liveConfirmed.map((ing) => (
                          <span className="live-chip confirmed" key={ing}>
                            <Check size={12} />{ing}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {liveDiscarded.length > 0 && (
                    <div className="live-chip-group">
                      <span className="live-group-label">Descartados (clic para volver a mostrar)</span>
                      <div className="live-chips">
                        {liveDiscarded.map((ing) => (
                          <button
                            type="button"
                            className="live-chip discarded"
                            key={ing}
                            onClick={() => restoreLiveIngredient(ing)}
                            title={`Volver a detectar ${ing}`}
                          >
                            <RotateCcw size={11} />{ing}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {(liveConfirmed.length > 0 || liveDiscarded.length > 0) && (
                    <button type="button" className="reset-live-button" onClick={resetLiveSession}>
                      <RotateCcw size={14} />Reiniciar sesión en vivo
                    </button>
                  )}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="panel-heading">
                <div><span className="step-number">02</span><h2>Resultados</h2></div>
                {inference !== null && <span className="format-tag">{inference.toFixed(0)} ms</span>}
              </div>
              {error && <div className="form-message"><Icon name="alert" />{error}</div>}
              {loading ? (
                <div className="analysis-loading" aria-label="Analizando imagen">
                  <div className="scanner-beam"><Camera size={28} /></div>
                  <div><strong>Analizando ingredientes</strong><span>Ejecutando detección YOLO11s...</span></div>
                  <div className="progress-track"><motion.span initial={{ width: "12%" }} animate={{ width: "88%" }} transition={{ duration: 1.6, ease: "easeInOut" }} /></div>
                </div>
              ) : !detections.length ? (
                <div className="empty-state">
                  <div className="empty-visual"><span>⌗</span></div>
                  <h3>Esperando una imagen</h3>
                  <p>Los ingredientes detectados aparecerán aquí.</p>
                </div>
              ) : (
                <>
                  <p className="detection-help">Selecciona los ingredientes que quieres guardar</p>
                  <div className="detection-list detection-cards">
                    {Array.from(
                      detections.reduce((groups, item) => {
                        if (!groups.has(item.ingredient_es)) groups.set(item.ingredient_es, []);
                        groups.get(item.ingredient_es).push(item);
                        return groups;
                      }, new Map()).entries(),
                    ).map(([ingredient, items]) => {
                      const item = items[0];
                      const selected = selectedDetections.includes(ingredient);
                      const maxConfidence = Math.max(...items.map((detection) => detection.confidence));
                      return (
                        <motion.div
                          className={selected ? "detection-card selected" : "detection-card"}
                          key={`${item.class_en}-${ingredient}`}
                          layout
                          initial={{ opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, x: 12 }}
                        >
                          <div className="detection-card-main">
                            <button
                              type="button"
                              className={selected ? "detection-check checked" : "detection-check"}
                              onClick={() => toggleDetection(ingredient)}
                              aria-label={`${selected ? "Deseleccionar" : "Seleccionar"} ${ingredient}`}
                              aria-pressed={selected}
                            >
                              {selected && <Check size={13} />}
                            </button>
                            <div className="detection-name">
                              <span>{ingredient[0]?.toUpperCase()}</span>
                              <div><strong>{ingredient}</strong><small>{item.class_en}{items.length > 1 ? ` · ${items.length} detecciones` : ""}</small></div>
                            </div>
                            <div className="confidence">
                              <b>{Math.round(maxConfidence * 100)}%</b>
                              <div><span style={{ width: `${maxConfidence * 100}%` }} /></div>
                              {items.length > 1 && <small className="confidence-list">{items.map((detection) => `${Math.round(detection.confidence * 100)}%`).join(" · ")}</small>}
                            </div>
                          </div>
                          <div className="detection-card-actions">
                            <button
                              type="button"
                              className={item.saved ? "detection-save saved" : "detection-save"}
                              onClick={() => saveDetection(ingredient)}
                              disabled={item.saved}
                            >
                              {item.saved ? <><Check size={14} />Guardado</> : <><Plus size={14} />Guardar</>}
                            </button>
                            <button
                              type="button"
                              className="detection-remove"
                              onClick={() => removeDetection(ingredient)}
                              aria-label={`Eliminar ${ingredient}`}
                            >
                              <Trash2 size={14} />Eliminar
                            </button>
                          </div>
                        </motion.div>
                      );
                    })}
                  </div>
                  <button
                    type="button"
                    className="save-selected-button"
                    onClick={saveSelected}
                    disabled={!selectedDetections.length}
                  >
                    <Plus size={16} />
                    Guardar seleccionados
                    <span>{selectedDetections.length}</span>
                  </button>
                </>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function Fridge({ token, notify }) {
  const [items, setItems] = useState([]);
  const [name, setName] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const load = () => apiRequest("/fridge/items", token).then(setItems).catch((requestError) => setError(requestError.message));
  useEffect(() => {
    load();
  }, [token]);

  const add = async (event) => {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      await apiRequest("/fridge/items", token, { method: "POST", body: JSON.stringify({ ingredient_es: name.trim().toLowerCase(), source: "manual", quantity }) });
      setName("");
      setQuantity(1);
      load();
      notify("Ingrediente añadido");
    } catch (requestError) {
      setError(requestError.message);
      notify(requestError.message, "error");
    }
  };

  const update = async (item, patch) => {
    await apiRequest(`/fridge/items/${item.id}`, token, { method: "PUT", body: JSON.stringify(patch) });
    load();
  };

  const remove = async (item) => {
    await apiRequest(`/fridge/items/${item.id}`, token, { method: "DELETE" });
    load();
    notify(`${item.ingredient_es} eliminado`);
  };

  const visibleItems = items.filter((item) =>
    item.ingredient_es.toLowerCase().includes(search.trim().toLowerCase()),
  );

  return (
    <div className="page">
      <PageHeader eyebrow="Inventario inteligente" title="Mi nevera" description="Añade, organiza y actualiza los ingredientes disponibles en tu cocina." action={<div className="count-badge"><b>{items.length}</b><span>ingredientes</span></div>} />
      <section className="panel add-panel">
        <form onSubmit={add}>
          <label><span>Ingrediente</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="Ej. tomate, pollo, huevos..." /></label>
          <label className="qty-label"><span>Cantidad</span><input type="number" min="1" max="99" value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} /></label>
          <button className="primary-button" type="submit"><Icon name="plus" />Añadir</button>
        </form>
      </section>
      {items.length > 0 && (
        <div className="inventory-toolbar">
          <div className="inventory-search"><Search size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar en mi nevera..." aria-label="Buscar ingrediente" /></div>
          <span>{visibleItems.length} de {items.length} ingredientes</span>
        </div>
      )}
      {error && <div className="form-message"><Icon name="alert" />{error}</div>}
      {visibleItems.length ? (
        <section className="inventory-grid">
          {visibleItems.map((item) => (
            <motion.article className="inventory-card" key={item.id} layout initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}>
              <div className="inventory-main">
                <div className="ingredient-avatar" aria-hidden="true">{ingredientIcon(item.ingredient_es)}</div>
                <div><h3>{item.ingredient_es}</h3><span>{item.source === "camera" ? "Detectado por cámara" : item.source === "manual" ? "Añadido manualmente" : "Despensa"}</span></div>
                <span className="inventory-status"><i />Disponible</span>
              </div>
              <div className="inventory-actions">
                <button onClick={() => update(item, { quantity: Math.max(1, item.quantity - 1) })}>−</button>
                <b>{item.quantity}</b>
                <button onClick={() => update(item, { quantity: Math.min(99, item.quantity + 1) })}>+</button>
                <button className="delete-button" onClick={() => remove(item)} title="Eliminar"><Icon name="trash" /></button>
              </div>
            </motion.article>
          ))}
        </section>
      ) : (
        <section className="panel empty-panel"><div className="empty-visual"><span>◫</span></div><h3>Tu nevera está vacía</h3><p>Añade ingredientes manualmente o escanea una foto.</p></section>
      )}
    </div>
  );
}

function Recipes({ token, notify }) {
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState("");
  const [maxMissing, setMaxMissing] = useState(3);
  const [topK, setTopK] = useState(5);
  const [recipes, setRecipes] = useState([]);
  const [favorites, setFavorites] = useState([]);
  const [tab, setTab] = useState("recommend");
  const [selectedRecipe, setSelectedRecipe] = useState(null);
  const [favoriteDetailMode, setFavoriteDetailMode] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiRequest("/categories", token).then((data) => setCategories(["Todas", ...data])).catch(() => {});
    apiRequest("/favorites", token).then(setFavorites).catch(() => {});
  }, [token]);

  useEffect(() => {
    if (!selectedRecipe) return;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setSelectedRecipe(null);
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.body.style.overflow = previousOverflow;
    };
  }, [selectedRecipe]);

  const recommend = async () => {
    setError("");
    const params = new URLSearchParams({ max_missing: maxMissing, top_k: topK });
    if (category && category !== "Todas") params.set("category", category);
    try {
      setRecipes(await apiRequest(`/recommend/from-fridge?${params}`, token));
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const favorite = async (recipe) => {
    await apiRequest("/favorites", token, { method: "POST", body: JSON.stringify({ recipe_id: recipe.recipe_id, notes: "" }) });
    setFavorites(await apiRequest("/favorites", token));
    notify("Receta guardada en favoritos");
  };

  const toggleFavorite = async (recipe) => {
    const existing = favorites.find((item) => item.recipe_id === recipe.recipe_id);
    if (existing) {
      await removeFavorite(existing);
      return;
    }
    await favorite(recipe);
  };

  const removeFavorite = async (favoriteItem) => {
    await apiRequest(`/favorites/${favoriteItem.id}`, token, { method: "DELETE" });
    setFavorites(await apiRequest("/favorites", token));
    notify("Favorito eliminado");
  };

  const openDetails = async (recipe) => {
    setDetailLoading(true);
    try {
      const detail = await apiRequest(`/recipes/${recipe.recipe_id}`, token);
      setFavoriteDetailMode(false);
      setSelectedRecipe({ ...recipe, ...detail });
    } catch (requestError) {
      notify(requestError.message, "error");
    } finally {
      setDetailLoading(false);
    }
  };

  const openFavoriteDetails = async (favoriteItem) => {
    setDetailLoading(true);
    try {
      const detail = await apiRequest(`/recipes/${favoriteItem.recipe_id}`, token);
      setFavoriteDetailMode(true);
      setSelectedRecipe(detail);
    } catch (requestError) {
      notify(requestError.message, "error");
    } finally {
      setDetailLoading(false);
    }
  };

  const recipePlaceholder = (cat) => {
    const normalized = String(cat).toLowerCase();
    if (normalized.includes("postre")) return "Postre";
    if (normalized.includes("pescado") || normalized.includes("marisco")) return "Mar";
    if (normalized.includes("verdura") || normalized.includes("ensalada")) return "Verdura";
    if (normalized.includes("pasta") || normalized.includes("arroz")) return "Cocina";
    return "Receta";
  };

  return (
    <div className="page">
      <PageHeader eyebrow="Cocina sin desperdicio" title="Recetas para ti" description="Encuentra platos que encajan con los ingredientes de tu nevera." />
      <div className="tab-bar"><button className={tab === "recommend" ? "active" : ""} onClick={() => setTab("recommend")}>Recomendadas</button><button className={tab === "favorites" ? "active" : ""} onClick={() => setTab("favorites")}>Favoritos <span>{favorites.length}</span></button></div>
      {tab === "recommend" ? (
        <>
          <section className="panel recipe-filters">
            <label><span>Categoría</span><select value={category} onChange={(event) => setCategory(event.target.value)}><option value="">Todas</option>{categories.filter((item) => item !== "Todas").map((item) => <option key={item}>{item}</option>)}</select></label>
            <label><span>Ingredientes faltantes</span><input type="range" min="0" max="10" value={maxMissing} onChange={(event) => setMaxMissing(Number(event.target.value))} /><b>{maxMissing}</b></label>
            <label><span>Resultados</span><select value={topK} onChange={(event) => setTopK(Number(event.target.value))}>{[3, 5, 8, 10, 15].map((value) => <option key={value} value={value}>{value} recetas</option>)}</select></label>
            <button className="primary-button" onClick={recommend}>Buscar recetas<span>→</span></button>
          </section>
          {error && <div className="form-message"><Icon name="alert" />{error}</div>}
          {recipes.length ? (
            <section className="recipe-grid">
              {recipes.map((recipe, index) => (
                <motion.article className="recipe-card" key={recipe.recipe_id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.055, duration: 0.28 }}>
                  <div className="recipe-visual" aria-label={`Imagen no disponible para ${recipe.title}`}>
                    <div className="recipe-placeholder-art"><ChefHat size={25} strokeWidth={1.5} /><span>{recipePlaceholder(recipe.category)}</span></div>
                    <span className="recipe-category">{recipe.category}</span>
                    <button
                      className={favorites.some((item) => item.recipe_id === recipe.recipe_id) ? "recipe-favorite active" : "recipe-favorite"}
                      onClick={() => toggleFavorite(recipe)}
                      title={favorites.some((item) => item.recipe_id === recipe.recipe_id) ? "Eliminar de favoritos" : "Guardar en favoritos"}
                      aria-label={favorites.some((item) => item.recipe_id === recipe.recipe_id) ? `Eliminar ${recipe.title} de favoritos` : `Guardar ${recipe.title} en favoritos`}
                      aria-pressed={favorites.some((item) => item.recipe_id === recipe.recipe_id)}
                    >
                      <Heart size={16} fill={favorites.some((item) => item.recipe_id === recipe.recipe_id) ? "currentColor" : "none"} />
                    </button>
                  </div>
                  <h3>{recipe.title}</h3>
                  <div className="compatibility-block">
                    <div className="match-row"><span>Cobertura de ingredientes</span><b>{recipe.match_pct}%</b></div>
                    <div className="match-track"><motion.span initial={{ width: 0 }} animate={{ width: `${recipe.match_pct}%` }} transition={{ duration: 0.55 }} /></div>
                  </div>
                  <div className="ingredient-pills"><b>Tienes</b>{recipe.matched_ingredients.slice(0, 5).map((item) => <span className="matched" key={item}>{item}</span>)}</div>
                  {recipe.missing_ingredients.length > 0 && <div className="ingredient-pills"><b>Faltan</b>{recipe.missing_ingredients.slice(0, 4).map((item) => <span key={item}>{item}</span>)}</div>}
                  <button className="recipe-detail-button" onClick={() => openDetails(recipe)} disabled={detailLoading}>Ver receta <ArrowRight size={15} /></button>
                </motion.article>
              ))}
            </section>
          ) : (
            <section className="panel empty-panel"><div className="empty-visual"><span>♨</span></div><h3>Listas para cocinar</h3><p>Busca recetas según los ingredientes de tu nevera.</p></section>
          )}
        </>
      ) : (
        <section className="favorites-section">
          {favorites.length ? (
            <>
              <div className="favorites-summary">
                <div><Heart size={18} fill="currentColor" /><span><b>{favorites.length}</b> receta{favorites.length === 1 ? "" : "s"} guardada{favorites.length === 1 ? "" : "s"}</span></div>
                <p>Tus recetas seleccionadas, listas para consultar.</p>
              </div>
              <div className="favorite-grid">
                {favorites.map((item, index) => (
                  <motion.article className="favorite-card" key={item.id} layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.05 }}>
                    <div className="favorite-card-visual">
                      <div className="favorite-placeholder"><ChefHat size={24} strokeWidth={1.5} /><span>Receta</span></div>
                      <button className="favorite-remove" onClick={() => removeFavorite(item)} title="Eliminar de favoritos" aria-label={`Eliminar ${item.dish_title} de favoritos`}><Heart size={16} fill="currentColor" /></button>
                    </div>
                    <div className="favorite-card-body">
                      <h3>{item.dish_title}</h3>
                      <span className="favorite-date">Guardada el {String(item.saved_at).slice(0, 10)}</span>
                      <button className="favorite-detail-button" onClick={() => openFavoriteDetails(item)} disabled={detailLoading}><ChefHat size={15} />Ver receta<ArrowRight size={14} /></button>
                    </div>
                  </motion.article>
                ))}
              </div>
            </>
          ) : (
            <div className="panel empty-panel"><div className="empty-visual"><span>♡</span></div><h3>Aún no tienes favoritos</h3><p>Guarda una receta desde el corazón de cada tarjeta.</p></div>
          )}
        </section>
      )}
      {selectedRecipe &&
        createPortal(
          <motion.div
            className="modal-backdrop"
            role="dialog"
            aria-modal="true"
            aria-label={`Detalles de ${selectedRecipe.title}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) setSelectedRecipe(null);
            }}
          >
            <motion.section
              className="recipe-modal"
              initial={{ opacity: 0, y: 12, scale: 0.99 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
            >
              <div className="modal-header">
                <div className="modal-title-wrap">
                  <div className="modal-recipe-icon"><ChefHat size={22} strokeWidth={1.6} /></div>
                  <div><span>{selectedRecipe.category}</span><h2>{selectedRecipe.title}</h2></div>
                </div>
                <button onClick={() => setSelectedRecipe(null)} aria-label="Cerrar detalles"><X size={18} /></button>
              </div>
              {favoriteDetailMode ? (
                <div className="modal-favorite-note"><Heart size={16} fill="currentColor" /><span>Receta guardada en favoritos</span></div>
              ) : (
                <>
                  <div className="modal-summary">
                    <div><span>Cobertura con tu nevera</span><strong>{selectedRecipe.match_pct}%</strong></div>
                    <div><span>Ingredientes disponibles</span><strong>{selectedRecipe.matched_ingredients?.length || 0}</strong></div>
                    <div><span>Ingredientes faltantes</span><strong>{selectedRecipe.missing_ingredients?.length || 0}</strong></div>
                  </div>
                  <div className="modal-match"><div><motion.span initial={{ width: 0 }} animate={{ width: `${selectedRecipe.match_pct}%` }} /></div></div>
                </>
              )}
              <div className="modal-columns">
                <section className="modal-ingredients-panel">
                  <div className="modal-section-heading"><span>01</span><h3>Ingredientes</h3></div>
                  <div className="modal-ingredients">{(selectedRecipe.parsed_ingredients || selectedRecipe.matched_ingredients || []).map((item) => <span key={item}>{item}</span>)}</div>
                </section>
                <section className="recipe-steps">
                  <div className="modal-section-heading"><span>02</span><h3>Instrucciones</h3></div>
                  <ol>{splitInstructions(selectedRecipe.instructions).map((step, index) => <li key={`${index}-${step.slice(0, 18)}`}><span>{index + 1}</span><p>{step}</p></li>)}</ol>
                </section>
              </div>
              {selectedRecipe.source_url && <a className="modal-source" href={selectedRecipe.source_url} target="_blank" rel="noreferrer">Abrir fuente original <ArrowRight size={15} /></a>}
            </motion.section>
          </motion.div>,
          document.body,
        )}
    </div>
  );
}

function Dashboard({ token }) {
  const [metrics, setMetrics] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    apiRequest("/ml/metrics", token).then(setMetrics).catch((requestError) => setError(requestError.message));
  }, [token]);
  if (error) return <div className="page"><div className="form-message"><Icon name="alert" />{error}</div></div>;
  if (!metrics) return <div className="page"><div className="loading-card">Cargando analítica...</div></div>;

  const classic = metrics.classic_ml || {};
  const yolo = metrics.yolo || {};
  const rec = metrics.recommender || {};
  const cv = [...(classic.cv_comparison || [])].sort((a, b) => b.f1_macro - a.f1_macro);

  const yoloName = (yolo.model || "yolo11s").toUpperCase();
  const yoloClasses = yolo.classes || 27;
  const yoloEpochs = yolo.epochs_configured || 80;

  const dMap50 = ((yolo.mAP50 || 0) - YOLOV8_BASELINE.mAP50) * 100;
  const dPrecision = ((yolo.precision || 0) - YOLOV8_BASELINE.precision) * 100;
  const dMap95 = ((yolo.mAP50_95 || 0) - YOLOV8_BASELINE.mAP50_95) * 100;
  const infCurrent = yolo.speed_ms?.inference || 0;
  const infBaseline = YOLOV8_BASELINE.speed_ms.inference;

  const yoloCompareData = [
    {
      metric: "Precision",
      YOLOv8n: Number((YOLOV8_BASELINE.precision * 100).toFixed(2)),
      [yoloName]: Number(((yolo.precision || 0) * 100).toFixed(2)),
    },
    {
      metric: "mAP@50",
      YOLOv8n: Number((YOLOV8_BASELINE.mAP50 * 100).toFixed(2)),
      [yoloName]: Number(((yolo.mAP50 || 0) * 100).toFixed(2)),
    },
    {
      metric: "F1 aprox.",
      YOLOv8n: Number((YOLOV8_BASELINE.f1_approx * 100).toFixed(2)),
      [yoloName]: Number(((yolo.f1_approx || 0) * 100).toFixed(2)),
    },
    {
      metric: "Recall",
      YOLOv8n: Number((YOLOV8_BASELINE.recall * 100).toFixed(2)),
      [yoloName]: Number(((yolo.recall || 0) * 100).toFixed(2)),
    },
    {
      metric: "mAP@50-95",
      YOLOv8n: Number((YOLOV8_BASELINE.mAP50_95 * 100).toFixed(2)),
      [yoloName]: Number(((yolo.mAP50_95 || 0) * 100).toFixed(2)),
    },
  ];

  return (
    <div className="page dashboard-page">
      <PageHeader
        eyebrow="Centro de inteligencia"
        title="Analítica del modelo"
        description={`Evolución de Deep Learning (${yoloName} · ${yoloClasses} clases), ML clásico y recomendador TF-IDF.`}
      />

      <section className="kpi-grid">
        <motion.article className="kpi-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <span className="kpi-icon teal"><Camera size={19} /></span>
          <div>
            <small>{yoloName} · mAP@50 (Test)</small>
            <strong>{((yolo.mAP50 || 0) * 100).toFixed(2)}%</strong>
            <b className={dMap50 >= 0 ? "delta-up" : "delta-down"}>{dMap50 >= 0 ? "+" : ""}{dMap50.toFixed(2)} pts vs YOLOv8n · 83% Val</b>
          </div>
        </motion.article>

        <motion.article className="kpi-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
          <span className="kpi-icon blue"><Check size={19} /></span>
          <div>
            <small>{yoloName} · Precision (Test)</small>
            <strong>{((yolo.precision || 0) * 100).toFixed(2)}%</strong>
            <b className={dPrecision >= 0 ? "delta-up" : "delta-down"}>{dPrecision >= 0 ? "+" : ""}{dPrecision.toFixed(2)} pts vs YOLOv8n</b>
          </div>
        </motion.article>

        <motion.article className="kpi-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <span className="kpi-icon amber"><Clock3 size={19} /></span>
          <div>
            <small>Inferencia {yoloName} (T4)</small>
            <strong>{infCurrent.toFixed(2)} ms</strong>
            <b>{dMap95 >= 0 ? "+" : ""}{dMap95.toFixed(2)} pts en mAP@50-95 · {yoloEpochs} ép.</b>
          </div>
        </motion.article>

        <motion.article className="kpi-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <span className="kpi-icon coral"><ChefHat size={19} /></span>
          <div>
            <small>Recomendador TF-IDF</small>
            <strong>{(rec.avg_latency_ms || 0).toFixed(2)} ms</strong>
            <b>Mejor ML clásico: 72.90% (HGB)</b>
          </div>
        </motion.article>
      </section>

      <section className="panel model-panel">
        <div className="panel-heading">
          <div>
            <span className="step-number">01</span>
            <h2>Evolución Deep Learning (Test): YOLOv8n vs. {yoloName}</h2>
          </div>
          <span className="format-tag">31 cl. / 35 ép. → {yoloClasses} cl. / {yoloEpochs} ép.</span>
        </div>
        <p className="section-explanation">
          Métricas medidas sobre el conjunto de Test inédito (en Validación, {yoloName} alcanza 83,00% mAP@50).
        </p>
        <div className="yolo-compare-grid">
          <div className="model-chart" role="img" aria-label="Comparativa YOLOv8n frente a YOLO11s">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={yoloCompareData} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
                <CartesianGrid stroke="#edf2f1" vertical={false} />
                <XAxis dataKey="metric" tick={{ fill: "#52677a", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis domain={[0, 100]} tick={{ fill: "#8797a3", fontSize: 10 }} axisLine={false} tickLine={false} unit="%" />
                <Tooltip cursor={{ fill: "#f4f8f7" }} formatter={(value) => [`${value}%`]} />
                <Legend wrapperStyle={{ fontSize: "11px" }} />
                <Bar dataKey="YOLOv8n" name="YOLOv8n (35 ép.)" fill="#90a4ae" radius={[6, 6, 0, 0]} barSize={22} />
                <Bar dataKey={yoloName} name={`${yoloName} (${yoloEpochs} ép.)`} fill="#1da58f" radius={[6, 6, 0, 0]} barSize={22} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="compare-table-wrap">
            <table className="compare-table">
              <thead>
                <tr>
                  <th>Métrica (Test)</th>
                  <th>YOLOv8n</th>
                  <th>{yoloName}</th>
                  <th>Δ</th>
                </tr>
              </thead>
              <tbody>
                {yoloCompareData.map((row) => {
                  const diff = row[yoloName] - row.YOLOv8n;
                  return (
                    <tr key={row.metric}>
                      <td>{row.metric}</td>
                      <td>{row.YOLOv8n.toFixed(2)}%</td>
                      <td><strong>{row[yoloName].toFixed(2)}%</strong></td>
                      <td className={diff >= 0 ? "delta-up" : "delta-down"}>
                        {diff >= 0 ? "+" : ""}{diff.toFixed(2)}
                      </td>
                    </tr>
                  );
                })}
                <tr>
                  <td>Inferencia T4</td>
                  <td>{infBaseline.toFixed(2)} ms</td>
                  <td><strong>{infCurrent.toFixed(2)} ms</strong></td>
                  <td className="delta-muted">
                    {infCurrent - infBaseline >= 0 ? "+" : ""}{(infCurrent - infBaseline).toFixed(2)} ms
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {cv.length > 0 && (
        <section className="panel model-panel">
          <div className="panel-heading"><div><span className="step-number">02</span><h2>Comparativa de modelos clásicos</h2></div><span className="format-tag">5-Fold CV</span></div>
          <div className="model-chart" role="img" aria-label="Comparativa de precisión de modelos clásicos">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={cv.map((item) => ({ name: item.model, valor: Number((item.f1_macro * 100).toFixed(1)) }))} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
                <CartesianGrid stroke="#edf2f1" horizontal={false} />
                <XAxis type="number" domain={[0, 100]} tick={{ fill: "#8797a3", fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" width={150} tick={{ fill: "#52677a", fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "#f4f8f7" }} formatter={(value) => [`${value}%`, "F1 macro"]} />
                <Bar dataKey="valor" radius={[0, 7, 7, 0]} barSize={18}>
                  {cv.map((_, index) => <Cell key={index} fill={index === 0 ? "#1da58f" : "#75bfb1"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {rec.funnel && (
        <section className="panel funnel-panel">
          <div className="panel-heading"><div><span className="step-number">03</span><h2>Calidad del corpus</h2></div><span className="format-tag">{rec.funnel.final_recipes.toLocaleString("es")} recetas</span></div>
          <p className="section-explanation">Proceso aplicado al corpus antes de generar recomendaciones.</p>
          <div className="corpus-flow">
            {Object.entries({
              "Recetas brutas": rec.funnel.raw,
              "Sin nulos": rec.funnel.non_null,
              "Recetas culinarias": rec.funnel.culinary,
              "Títulos únicos": rec.funnel.unique_titles,
              "Corpus final": rec.funnel.final_recipes,
            }).map(([label, value], index, entries) => {
              const retained = rec.funnel.raw ? (value / rec.funnel.raw) * 100 : 0;
              return (
                <div className="corpus-step" key={label}>
                  <div className="corpus-node"><span>{String(index + 1).padStart(2, "0")}</span><b>{value.toLocaleString("es")}</b><small>{label}</small></div>
                  <div className="corpus-retention">{retained.toFixed(1)}% retenido</div>
                  {index < entries.length - 1 && <div className="corpus-arrow" aria-hidden="true"><ArrowRight size={14} /></div>}
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

export default App;