import io
import json
import time
from pathlib import Path
from typing import Optional

import cv2
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont, ImageOps

st.set_page_config(
    page_title="Smart Fridge RAIA",
    page_icon="🧊",
    layout="wide",
)

# -------------------- CONFIGURACIÓN Y SESIÓN --------------------
if "api_url" not in st.session_state:
    st.session_state.api_url = "http://127.0.0.1:8000"
if "token" not in st.session_state:
    st.session_state.token = None
if "username" not in st.session_state:
    st.session_state.username = None

# Estado del modo Live
if "live_active" not in st.session_state:
    st.session_state.live_active = False
if "live_cap" not in st.session_state:
    st.session_state.live_cap = None
if "live_discarded" not in st.session_state:
    st.session_state.live_discarded = set()
if "live_confirmed" not in st.session_state:
    st.session_state.live_confirmed = set()
if "live_seen" not in st.session_state:
    st.session_state.live_seen = {}


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"} if st.session_state.token else {}


def api_request(method: str, path: str, **kwargs):
    url = f"{st.session_state.api_url.rstrip('/')}{path}"
    headers = kwargs.pop("headers", {})
    headers.update(auth_headers())
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        return resp
    except requests.RequestException as exc:
        st.error(f"Error de conexión con FastAPI ({url}): {exc}")
        return None


def open_camera(cam_index: int = 0):
    cap = cv2.VideoCapture(cam_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(cam_index)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap
    return None


def release_camera():
    cap = st.session_state.get("live_cap")
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass
        st.session_state.live_cap = None
    st.session_state.live_active = False


@st.cache_resource
def _get_font(size: int = 16):
    for font_name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_detections(
    image_bytes: bytes,
    detections: list,
    confirmed_set: Optional[set] = None,
    live_mode: bool = False,
) -> Image.Image:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = _get_font(16)
    confirmed_set = confirmed_set or set()

    for det in detections:
        x1, y1, x2, y2 = det["bbox"]
        ing = det["ingredient_es"]
        is_confirmed = ing in confirmed_set

        if is_confirmed:
            color = "#00E676"  # Verde: ya guardado en nevera
            label = f"✓ {ing.capitalize()} ({det['confidence']*100:.0f}%)"
        elif live_mode:
            color = "#00B0FF"  # Azul: pendiente de confirmar/descartar
            label = f"{ing.capitalize()} ({det['confidence']*100:.0f}%)"
        else:
            color = "#00E676"
            label = f"{ing.capitalize()} ({det['confidence']*100:.0f}%)"

        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        bbox_txt = draw.textbbox((0, 0), label, font=font)
        tw = bbox_txt[2] - bbox_txt[0]
        th = bbox_txt[3] - bbox_txt[1]
        text_y = max(0, y1 - th - 8)
        draw.rectangle([x1, text_y, x1 + tw + 10, text_y + th + 8], fill=color)
        draw.text((x1 + 5, text_y + 3), label, fill="#000000", font=font)
    return img


# -------------------- BARRA LATERAL (LOGIN + NAVEGACIÓN) --------------------
with st.sidebar:
    st.title("🧊 Smart Fridge RAIA")
    st.session_state.api_url = st.text_input("URL del Backend FastAPI", st.session_state.api_url)

    health_resp = api_request("GET", "/health")
    if health_resp and health_resp.status_code == 200:
        h = health_resp.json()
        st.success(f"API Online | {h['recipes_loaded']:,} recetas | {h['visual_classes']} clases")
    else:
        st.warning("Backend desconectado. Arranca Uvicorn en el puerto 8000.")

    st.divider()

    if not st.session_state.token:
        st.subheader("Iniciar Sesión")
        tab_login, tab_reg = st.tabs(["Entrar", "Registro"])
        with tab_login:
            u = st.text_input("Usuario", value="demo", key="login_u")
            p = st.text_input("Contraseña", value="demo1234", type="password", key="login_p")
            if st.button("Acceder", use_container_width=True):
                r = api_request("POST", "/token", data={"username": u, "password": p})
                if r and r.status_code == 200:
                    st.session_state.token = r.json()["access_token"]
                    st.session_state.username = u
                    st.rerun()
                elif r:
                    st.error(r.json().get("detail", "Credenciales incorrectas"))
        with tab_reg:
            ru = st.text_input("Nuevo usuario", key="reg_u")
            rp = st.text_input("Nueva contraseña (mín. 6)", type="password", key="reg_p")
            if st.button("Crear cuenta", use_container_width=True):
                r = api_request("POST", "/register", json={"username": ru, "password": rp})
                if r and r.status_code == 201:
                    st.success("Usuario creado. Ya puedes iniciar sesión.")
                elif r:
                    st.error(r.json().get("detail", "No se pudo registrar"))
    else:
        st.info(f"Sesión activa: **{st.session_state.username}**")
        if st.button("Cerrar sesión", use_container_width=True):
            release_camera()
            st.session_state.token = None
            st.session_state.username = None
            st.rerun()

    st.divider()
    page = st.radio(
        "Navegación",
        [
            "📷 Escáner Visual (YOLO)",
            "🥬 Mi Nevera",
            "🍳 Recetas y Favoritos",
            "📊 Dashboard ML",
        ],
    )

# Liberar webcam automáticamente si el usuario cambia de pestaña
if page != "📷 Escáner Visual (YOLO)" and st.session_state.live_active:
    release_camera()


# -------------------- PÁGINA 1: ESCÁNER VISUAL --------------------
if page == "📷 Escáner Visual (YOLO)":
    st.header("📷 Escáner de Ingredientes con YOLO11s")
    if not st.session_state.token:
        st.warning("Inicia sesión en la barra lateral (`demo` / `demo1234`) para escanear.")
        st.stop()

    source_mode = st.radio(
        "Modo de escaneo",
        ["🎥 Cámara en vivo (Live)", "Subir foto", "Foto única (Webcam)"],
        horizontal=True,
    )

    if source_mode != "🎥 Cámara en vivo (Live)" and st.session_state.live_active:
        release_camera()

    # ==================== MODO LIVE INTERACTIVO ====================
    if source_mode == "🎥 Cámara en vivo (Live)":
        c_ctrl1, c_ctrl2, c_ctrl3, c_ctrl4 = st.columns([2, 2, 2, 2])
        with c_ctrl1:
            live_conf = st.slider(
                "Umbral de confianza",
                min_value=0.05,
                max_value=0.80,
                value=0.20,
                step=0.05,
                key="live_conf",
            )
        with c_ctrl2:
            live_enhance = st.checkbox("Mejorar luz (CLAHE)", value=True, key="live_enhance")
            fast_mode = st.checkbox(
                "Modo rápido (480px)",
                value=True,
                key="live_fast",
                help="Acelera los FPS en CPU; desmárcalo para máxima precisión a 640px.",
            )
        with c_ctrl3:
            cam_idx = st.number_input("Índice cámara", min_value=0, max_value=4, value=0, step=1)
        with c_ctrl4:
            st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
            if not st.session_state.live_active:
                if st.button("▶️ Iniciar cámara en vivo", type="primary", use_container_width=True):
                    cap = open_camera(int(cam_idx))
                    if cap is None:
                        st.error("No se pudo abrir la webcam. Comprueba que ninguna otra app la esté usando.")
                    else:
                        st.session_state.live_cap = cap
                        st.session_state.live_active = True
                        st.rerun()
            else:
                if st.button("⏹️ Detener cámara", type="secondary", use_container_width=True):
                    release_camera()
                    st.rerun()

        if not st.session_state.live_active:
            st.info(
                "Pulsa **▶️ Iniciar cámara en vivo** para mover los alimentos frente a la cámara. "
                "Podrás **✅ Confirmar** los aciertos para guardarlos en Mi Nevera y **❌ Descartar** "
                "cualquier clase confundida (ej. descartar *limón* para quedarte solo con *manzana*)."
            )
        else:
            @st.fragment(run_every=0.25)
            def live_scanner_panel():
                cap = st.session_state.get("live_cap")
                if not st.session_state.live_active or cap is None or not cap.isOpened():
                    return

                # Vaciar 2 frames del buffer interno para ver siempre la imagen más reciente
                for _ in range(2):
                    cap.grab()
                ok, frame_bgr = cap.read()
                if not ok or frame_bgr is None:
                    st.warning("Esperando fotograma de la webcam...")
                    return

                ok_enc, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if not ok_enc:
                    return
                frame_bytes = buf.tobytes()

                r = api_request(
                    "POST",
                    "/recognize",
                    params={
                        "conf": live_conf,
                        "enhance": str(live_enhance).lower(),
                        "tta": "false",
                        "imgsz": 480 if fast_mode else 640,
                        "log_scan": "false",
                    },
                    files={"image": ("live.jpg", frame_bytes, "image/jpeg")},
                )

                dets_raw = []
                inf_ms = 0.0
                if r and r.status_code == 200:
                    payload = r.json()
                    dets_raw = payload["detected_items"]
                    inf_ms = payload["inference_ms"]

                # Filtrar las clases que el usuario ya descartó en esta sesión
                discarded = st.session_state.live_discarded
                confirmed = st.session_state.live_confirmed
                visible_dets = [d for d in dets_raw if d["ingredient_es"] not in discarded]

                now = time.time()
                current_ings = set()
                for d in visible_dets:
                    ing = d["ingredient_es"]
                    current_ings.add(ing)
                    prev = st.session_state.live_seen.get(ing)
                    st.session_state.live_seen[ing] = {
                        "class_en": d["class_en"],
                        "last_conf": d["confidence"],
                        "max_conf": max(d["confidence"], prev["max_conf"]) if prev else d["confidence"],
                        "last_seen": now,
                    }

                # Mantener candidatos recientes 8 segundos para que los botones no desaparezcan al mover el objeto
                st.session_state.live_seen = {
                    ing: info
                    for ing, info in st.session_state.live_seen.items()
                    if ing not in discarded and (now - info["last_seen"] <= 8.0 or ing in confirmed)
                }

                col_vid, col_panel = st.columns([3, 2])

                with col_vid:
                    annotated = draw_detections(
                        frame_bytes,
                        visible_dets,
                        confirmed_set=confirmed,
                        live_mode=True,
                    )
                    st.image(
                        annotated,
                        caption=(
                            f"LIVE · Inferencia: {inf_ms:.0f} ms · "
                            f"{len(visible_dets)} visibles · {len(discarded)} descartados"
                        ),
                        use_container_width=True,
                    )

                with col_panel:
                    st.subheader("Detecciones en vivo")
                    pending = {
                        ing: info
                        for ing, info in st.session_state.live_seen.items()
                        if ing not in confirmed
                    }

                    if not pending:
                        st.info("Mueve un alimento frente a la cámara para detectarlo...")
                    else:
                        st.caption("Confirma para guardar en tu nevera o descarta para ocultar del vídeo:")
                        # Orden alfabético fijo para que los botones no cambien de posición al hacer clic
                        for ing in sorted(pending.keys()):
                            info = pending[ing]
                            live_dot = "🟢" if ing in current_ings else "🕒"
                            p1, p2, p3 = st.columns([3, 1, 1])
                            p1.markdown(
                                f"{live_dot} **{ing.capitalize()}** "
                                f"`{info['last_conf']*100:.0f}%`"
                            )
                            if p2.button("✅", key=f"live_ok_{ing}", help=f"Confirmar y añadir {ing} a Mi Nevera"):
                                resp = api_request(
                                    "POST",
                                    "/fridge/items",
                                    json={"ingredient_es": ing, "source": "camera", "quantity": 1},
                                )
                                if resp and resp.status_code == 201:
                                    st.session_state.live_confirmed.add(ing)
                                    st.rerun()
                            if p3.button("❌", key=f"live_no_{ing}", help=f"Descartar {ing} del vídeo en vivo"):
                                st.session_state.live_discarded.add(ing)
                                st.session_state.live_seen.pop(ing, None)
                                st.rerun()

                    st.divider()

                    # Resumen de confirmados en esta sesión
                    if confirmed:
                        st.markdown(
                            "**✅ Guardados en Mi Nevera:** "
                            + ", ".join(f"`{i.capitalize()}`" for i in sorted(confirmed))
                        )

                    # Resumen de descartados con opción de restaurar
                    if discarded:
                        st.markdown("**🚫 Descartados (ocultos del vídeo):**")
                        d_cols = st.columns(min(len(discarded), 3))
                        for idx, ing in enumerate(sorted(discarded)):
                            if d_cols[idx % len(d_cols)].button(
                                f"↩️ {ing.capitalize()}",
                                key=f"live_res_{ing}",
                                help=f"Volver a mostrar {ing}",
                                use_container_width=True,
                            ):
                                st.session_state.live_discarded.discard(ing)
                                st.rerun()

                    if confirmed or discarded:
                        if st.button("🔄 Reiniciar sesión Live", use_container_width=True):
                            st.session_state.live_discarded.clear()
                            st.session_state.live_confirmed.clear()
                            st.session_state.live_seen.clear()
                            st.rerun()

            live_scanner_panel()

    # ==================== MODO FOTO (SUBIR O WEBCAM ÚNICA) ====================
    else:
        is_cam_snap = source_mode == "Foto única (Webcam)"
        col_cfg1, col_cfg2 = st.columns([2, 2])
        with col_cfg1:
            conf = st.slider(
                "Umbral de confianza",
                min_value=0.05,
                max_value=0.90,
                value=0.15 if is_cam_snap else 0.30,
                step=0.05,
                key=f"conf_{source_mode}",
            )
        with col_cfg2:
            st.markdown("**Mejoras en inferencia**")
            enhance = st.checkbox(
                "Mejorar iluminación (CLAHE)",
                value=is_cam_snap,
                key=f"enh_{source_mode}",
                help="Corrige contraste en espacio LAB sin distorsionar colores.",
            )
            tta = st.checkbox(
                "Multi-escala TTA (augment)",
                value=is_cam_snap,
                key=f"tta_{source_mode}",
                help="Evalúa varias escalas y giros; más lento en CPU pero rescata detecciones dudosas.",
            )

        img_file = (
            st.file_uploader("Sube una foto del frigorífico", type=["jpg", "jpeg", "png", "webp"])
            if not is_cam_snap
            else st.camera_input("Captura desde tu cámara")
        )

        if img_file is not None:
            raw_bytes = img_file.getvalue()
            if st.button("🔍 Detectar ingredientes", type="primary"):
                with st.spinner("Ejecutando inferencia YOLO11s en FastAPI..."):
                    r = api_request(
                        "POST",
                        "/recognize",
                        params={
                            "conf": conf,
                            "enhance": str(enhance).lower(),
                            "tta": str(tta).lower(),
                        },
                        files={"image": (img_file.name, raw_bytes, img_file.type or "image/jpeg")},
                    )
                if r and r.status_code == 200:
                    st.session_state["last_scan"] = {
                        "raw_bytes": raw_bytes,
                        "res": r.json(),
                        "cfg": {"conf": conf, "enhance": enhance, "tta": tta},
                    }
                elif r:
                    st.error(r.json().get("detail", "Error en la detección"))

        last_scan = st.session_state.get("last_scan")
        if isinstance(last_scan, dict):
            raw_bytes = last_scan["raw_bytes"]
            res = last_scan["res"]
            scan_cfg = last_scan["cfg"]
            dets = res["detected_items"]
            c1, c2 = st.columns([3, 2])
            with c1:
                annotated = draw_detections(raw_bytes, dets)
                flags = (
                    f"CLAHE: {'Sí' if scan_cfg['enhance'] else 'No'} | "
                    f"TTA: {'Sí' if scan_cfg['tta'] else 'No'} | "
                    f"conf ≥ {scan_cfg['conf']:.2f}"
                )
                st.image(
                    annotated,
                    caption=f"Inferencia: {res['inference_ms']} ms | {len(dets)} detecciones | {flags}",
                    use_container_width=True,
                )
            with c2:
                st.subheader("Ingredientes detectados")
                if not dets:
                    st.info("No se detectaron ingredientes. Prueba a bajar el umbral a 0.10 o mejorar la iluminación.")
                else:
                    df_det = pd.DataFrame(dets)[["ingredient_es", "class_en", "confidence"]].copy()
                    df_det["confidence"] = (df_det["confidence"] * 100).map(lambda v: f"{v:.1f}%")
                    st.dataframe(df_det, use_container_width=True, hide_index=True)

                    unique_ings = sorted({d["ingredient_es"] for d in dets})
                    selected = st.multiselect("Seleccionar para añadir a Mi Nevera", unique_ings, default=unique_ings)
                    if st.button("➕ Guardar seleccionados en Mi Nevera", use_container_width=True):
                        added = 0
                        for ing in selected:
                            resp = api_request(
                                "POST",
                                "/fridge/items",
                                json={"ingredient_es": ing, "source": "camera", "quantity": 1},
                            )
                            if resp and resp.status_code == 201:
                                added += 1
                        st.success(f"{added} ingredientes guardados en tu nevera.")


# -------------------- PÁGINA 2: MI NEVERA (CRUD) --------------------
elif page == "🥬 Mi Nevera":
    st.header("🥬 Inventario de Mi Nevera")
    if not st.session_state.token:
        st.warning("Inicia sesión en la barra lateral para gestionar tu nevera.")
        st.stop()

    with st.form("add_manual_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([3, 1, 2, 1])
        ing_name = c1.text_input("Ingrediente (en español, ej. tomate, pollo, huevo)")
        qty = c2.number_input("Cantidad", min_value=1, max_value=99, value=1)
        src = c3.selectbox("Origen", ["manual", "camera", "pantry"])
        submitted = c4.form_submit_button("Añadir", use_container_width=True)
        if submitted and ing_name.strip():
            r = api_request(
                "POST",
                "/fridge/items",
                json={"ingredient_es": ing_name.strip().lower(), "source": src, "quantity": int(qty)},
            )
            if r and r.status_code == 201:
                st.success(f"Añadido: {ing_name}")
                st.rerun()

    r = api_request("GET", "/fridge/items")
    items = r.json() if (r and r.status_code == 200) else []

    if not items:
        st.info("Tu nevera está vacía. Escanea una foto o añade ingredientes arriba.")
    else:
        for item in items:
            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
            col1.markdown(f"**{item['ingredient_es'].capitalize()}** `{item['source']}`")
            new_q = col2.number_input(
                "Cant.",
                min_value=1,
                max_value=99,
                value=item["quantity"],
                key=f"qty_{item['id']}",
                label_visibility="collapsed",
            )
            if col3.button("💾", key=f"save_{item['id']}", help="Actualizar cantidad"):
                api_request("PUT", f"/fridge/items/{item['id']}", json={"quantity": int(new_q)})
                st.rerun()
            if col4.button("🗑️", key=f"del_{item['id']}", help="Eliminar"):
                api_request("DELETE", f"/fridge/items/{item['id']}")
                st.rerun()


# -------------------- PÁGINA 3: RECETAS Y FAVORITOS --------------------
elif page == "🍳 Recetas y Favoritos":
    st.header("🍳 Recomendador de Recetas (TF-IDF + Coseno)")
    if not st.session_state.token:
        st.warning("Inicia sesión en la barra lateral para ver recomendaciones y favoritos.")
        st.stop()

    tab_rec, tab_fav = st.tabs(["🔎 Recomendar desde Mi Nevera", "⭐ Mis Favoritos"])

    with tab_rec:
        cats_r = api_request("GET", "/categories")
        categories = ["Todas"] + (cats_r.json() if (cats_r and cats_r.status_code == 200) else [])

        f1, f2, f3 = st.columns(3)
        max_missing = f1.slider("Máx. ingredientes faltantes", 0, 10, 3)
        top_k = f2.slider("Número de recetas", 1, 15, 5)
        cat_sel = f3.selectbox("Categoría", categories)

        params = {"max_missing": max_missing, "top_k": top_k}
        if cat_sel != "Todas":
            params["category"] = cat_sel

        if st.button("✨ Buscar recetas", type="primary"):
            r = api_request("GET", "/recommend/from-fridge", params=params)
            if r and r.status_code == 200:
                st.session_state["last_recs"] = r.json()
            elif r:
                st.warning(r.json().get("detail", "No se pudieron obtener recetas."))

        for rec in st.session_state.get("last_recs", []):
            with st.expander(
                f"🍽️ {rec['title']} — **{rec['match_pct']}% cobertura** | Sim: {rec['cosine_sim']} | Faltan: {len(rec['missing_ingredients'])}"
            ):
                m1, m2 = st.columns(2)
                m1.markdown(f"**Tienes:** {', '.join(rec['matched_ingredients'])}")
                m2.markdown(
                    f"**Faltan:** {', '.join(rec['missing_ingredients']) if rec['missing_ingredients'] else '¡Nada! Tienes todo'}"
                )
                st.markdown("**Instrucciones:**")
                st.write(rec["instructions"])
                if rec.get("source_url"):
                    st.markdown(f"[Ver receta original]({rec['source_url']})")
                if st.button("⭐ Guardar en Favoritos", key=f"fav_btn_{rec['recipe_id']}"):
                    fr = api_request("POST", "/favorites", json={"recipe_id": rec["recipe_id"], "notes": ""})
                    if fr and fr.status_code == 201:
                        st.success("Guardada en favoritos.")

    with tab_fav:
        fr = api_request("GET", "/favorites")
        favs = fr.json() if (fr and fr.status_code == 200) else []
        if not favs:
            st.info("Aún no tienes recetas favoritas guardadas.")
        for fav in favs:
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"⭐ **{fav['dish_title']}** *(guardada el {fav['saved_at'][:10]})*")
            if c2.button("Eliminar", key=f"delfav_{fav['id']}"):
                api_request("DELETE", f"/favorites/{fav['id']}")
                st.rerun()


# -------------------- PÁGINA 4: DASHBOARD ML --------------------
elif page == "📊 Dashboard ML":
    st.header("📊 Laboratorio y Métricas de Machine Learning")
    r = api_request("GET", "/ml/metrics")
    if not r or r.status_code != 200:
        st.error("No se pudieron cargar las métricas desde `/ml/metrics`.")
        st.stop()

    metrics = r.json()

    yolo = metrics.get("yolo", {})
    classic = metrics.get("classic_ml", {})
    rec_m = metrics.get("recommender", {})

    v8_fallback = {
        "model": "yolov8n",
        "classes": 31,
        "epochs_configured": 35,
        "mAP50": 0.7639,
        "mAP50_95": 0.5439,
        "precision": 0.7567,
        "recall": 0.7184,
        "f1_approx": 0.7371,
        "speed_ms": {"inference": 4.36},
    }
    v8_path = Path(__file__).resolve().parent.parent / "artifacts" / "yolo_metrics_yolov8n.json"
    if v8_path.exists():
        with open(v8_path, "r", encoding="utf-8") as f:
            yolo_v8 = {**v8_fallback, **json.load(f)}
    else:
        yolo_v8 = v8_fallback

    yolo_name = yolo.get("model", "yolo11s").upper()
    yolo_classes = yolo.get("classes", 27)
    yolo_epochs = yolo.get("epochs_configured", 80)

    d_map50 = (yolo.get("mAP50", 0) - yolo_v8.get("mAP50", 0)) * 100
    d_prec = (yolo.get("precision", 0) - yolo_v8.get("precision", 0)) * 100
    d_map95 = (yolo.get("mAP50_95", 0) - yolo_v8.get("mAP50_95", 0)) * 100
    inf_v11 = yolo.get("speed_ms", {}).get("inference", 0)
    inf_v8 = yolo_v8.get("speed_ms", {}).get("inference", 4.36)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        f"{yolo_name} mAP@50 (Test · {yolo_classes} cl.)",
        f"{yolo.get('mAP50', 0)*100:.2f}%",
        delta=f"{d_map50:+.2f} pts vs YOLOv8n",
    )
    k2.metric(
        f"{yolo_name} Precision (Test)",
        f"{yolo.get('precision', 0)*100:.2f}%",
        delta=f"{d_prec:+.2f} pts vs YOLOv8n",
    )
    k3.metric(
        f"{yolo_name} mAP@50-95 (Test)",
        f"{yolo.get('mAP50_95', 0)*100:.2f}%",
        delta=f"{d_map95:+.2f} pts vs YOLOv8n",
    )
    k4.metric(
        f"Inferencia {yolo_name} (GPU T4)",
        f"{inf_v11:.2f} ms",
        delta=f"{inf_v11 - inf_v8:+.2f} ms vs YOLOv8n",
        delta_color="inverse",
    )

    st.caption(
        f"Nota: Todas las métricas mostradas en la comparativa están medidas sobre el conjunto de **Test** "
        f"(en Validación, **{yolo_name}** alcanza **83,00% mAP@50**). "
        f"Recomendador TF-IDF: **{rec_m.get('avg_latency_ms', 0):.2f} ms/consulta** · "
        f"Mejor ML clásico (12 clases): **72,90%** (`HistGradientBoosting`)."
    )

    if yolo:
        st.subheader(f"Evolución Deep Learning (Test): YOLOv8n (35 ép.) vs. {yolo_name} ({yolo_epochs} ép.)")

        metric_keys = [
            ("Precision", "precision"),
            ("mAP@50", "mAP50"),
            ("F1 aprox.", "f1_approx"),
            ("Recall", "recall"),
            ("mAP@50-95", "mAP50_95"),
        ]

        rows_cmp = []
        for label, key in metric_keys:
            rows_cmp.append(
                {
                    "Métrica": label,
                    "Modelo": "YOLOv8n (31 clases, 35 ép.)",
                    "Valor": yolo_v8.get(key, 0) * 100,
                }
            )
            rows_cmp.append(
                {
                    "Métrica": label,
                    "Modelo": f"{yolo_name} ({yolo_classes} clases, {yolo_epochs} ép.)",
                    "Valor": yolo.get(key, 0) * 100,
                }
            )

        df_cmp = pd.DataFrame(rows_cmp)

        col_g, col_t = st.columns([3, 2])
        with col_g:
            fig_cmp = px.bar(
                df_cmp,
                x="Métrica",
                y="Valor",
                color="Modelo",
                barmode="group",
                text=df_cmp["Valor"].map(lambda v: f"{v:.2f}%"),
                color_discrete_sequence=["#607D8B", "#00BFA5"],
                range_y=[0, 100],
                labels={"Valor": "Porcentaje (%)"},
            )
            fig_cmp.update_layout(
                height=360,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_cmp, use_container_width=True)

        with col_t:
            table_rows = []
            for label, key in metric_keys:
                v8_val = yolo_v8.get(key, 0) * 100
                v11_val = yolo.get(key, 0) * 100
                table_rows.append(
                    {
                        "Métrica": label,
                        "YOLOv8n": f"{v8_val:.2f}%",
                        yolo_name: f"{v11_val:.2f}%",
                        "Δ (pts)": f"{v11_val - v8_val:+.2f}",
                    }
                )
            table_rows.append(
                {
                    "Métrica": "Inferencia GPU T4",
                    "YOLOv8n": f"{inf_v8:.2f} ms",
                    yolo_name: f"{inf_v11:.2f} ms",
                    "Δ (pts)": f"{inf_v11 - inf_v8:+.2f} ms",
                }
            )
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    st.divider()

    if classic:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Comparativa 7 Modelos Clásicos (5-Fold CV)")
            df_cv = pd.DataFrame(classic["cv_comparison"]).sort_values("f1_macro", ascending=True)
            fig_cv = px.bar(
                df_cv,
                x="f1_macro",
                y="model",
                orientation="h",
                text="f1_macro",
                color="f1_macro",
                color_continuous_scale="Teal",
            )
            st.plotly_chart(fig_cv, use_container_width=True)

        with c2:
            st.subheader("Estudio de Ablación de Features (SVM RBF)")
            df_ab = pd.DataFrame.from_dict(classic["ablation"], orient="index").reset_index()
            df_ab.columns = ["Feature", "n_features", "accuracy", "f1_macro", "train_s", "pred_s"]
            fig_ab = px.bar(
                df_ab,
                x="Feature",
                y="accuracy",
                text="accuracy",
                color="accuracy",
                color_continuous_scale="Blues",
            )
            st.plotly_chart(fig_ab, use_container_width=True)

        st.subheader("Matriz de Confusión — HistGradientBoosting (Top-12)")
        fig_cm = px.imshow(
            classic["confusion_matrix"],
            x=classic["classes"],
            y=classic["classes"],
            text_auto=True,
            color_continuous_scale="Blues",
            aspect="auto",
        )
        st.plotly_chart(fig_cm, use_container_width=True)

    if rec_m:
        st.subheader("Embudo de Limpieza del Corpus de Recetas")
        funnel = rec_m["funnel"]
        df_f = pd.DataFrame(
            {
                "Etapa": ["Brutas", "Sin nulos", "Culinarias", "Títulos únicos", "Final (>=2 ing.)"],
                "Recetas": [
                    funnel["raw"],
                    funnel["non_null"],
                    funnel["culinary"],
                    funnel["unique_titles"],
                    funnel["final_recipes"],
                ],
            }
        )
        st.plotly_chart(px.funnel(df_f, x="Recetas", y="Etapa"), use_container_width=True)