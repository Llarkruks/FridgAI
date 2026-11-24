import json
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from backend.auth import create_access_token, get_current_user, hash_password, verify_password
from backend.database import get_db, init_db
from backend.ml_engine import ml_engine
from backend.assistant import generate_chat_response
from backend.schemas import ChatRequest, ChatResponse
from backend.schemas import (
    FavoriteCreate,
    FavoriteResponse,
    FridgeItemCreate,
    FridgeItemResponse,
    FridgeItemUpdate,
    RecipeDetailResponse,
    RecipeRecommendation,
    RecognitionResponse,
    RecommendationRequest,
    Token,
    UserCreate,
    UserResponse,
)

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MiB


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Crea usuario demo por defecto para pruebas rápidas en Unity / Streamlit
    with get_db() as conn:
        exists = conn.execute("SELECT id FROM users WHERE username = 'demo'").fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO users (username, hashed_password) VALUES (?, ?)",
                ("demo", hash_password("demo1234")),
            )
    ml_engine.load_all()
    yield


app = FastAPI(
    title="Smart Fridge RAIA API",
    description="Backend desacoplado de Visión por Computador (YOLOv8n) y Recomendación de Recetas (TF-IDF).",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permitir Unity y Streamlit en entorno local/red LAN
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------- SALUD Y CATÁLOGO PÚBLICO --------------------

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "yolo_loaded": ml_engine.yolo_model is not None,
        "recipes_loaded": len(ml_engine.recipes_df) if ml_engine.recipes_df is not None else 0,
        "visual_classes": len(ml_engine.yolo_to_es),
    }


@app.get("/categories", response_model=List[str])
def list_categories():
    return ml_engine.get_categories()


@app.get("/ml/metrics")
def get_ml_metrics():
    return ml_engine.get_ml_metrics()


# -------------------- AUTENTICACIÓN (OAuth2 + JWT) --------------------

@app.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user: UserCreate):
    with get_db() as conn:
        exists = conn.execute(
            "SELECT id FROM users WHERE username = ?", (user.username,)
        ).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="El usuario ya existe")
        cur = conn.execute(
            "INSERT INTO users (username, hashed_password) VALUES (?, ?)",
            (user.username, hash_password(user.password)),
        )
        return {"id": cur.lastrowid, "username": user.username}


@app.post("/token", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, username, hashed_password FROM users WHERE username = ?",
            (form_data.username,),
        ).fetchone()
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({"sub": user["username"]})
    return {"access_token": token, "token_type": "bearer"}


# -------------------- VISIÓN POR COMPUTADOR (YOLO) --------------------

@app.post("/recognize", response_model=RecognitionResponse)
async def recognize_ingredients(
    image: UploadFile = File(...),
    conf: float = Query(0.30, ge=0.05, le=0.95),
    current_user: dict = Depends(get_current_user),
):
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen válida (image/*)")

    raw_bytes = await image.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="La imagen enviada está vacía")
    if len(raw_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="La imagen supera el límite máximo de 5 MiB")

    try:
        inference_ms, detected = ml_engine.recognize_image(raw_bytes, conf=conf)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo procesar la imagen: {exc}")

    # Auditoría en scan_logs para estadísticas reales
    with get_db() as conn:
        conn.execute(
            "INSERT INTO scan_logs (user_id, detected_json, inference_ms) VALUES (?, ?, ?)",
            (current_user["id"], json.dumps(detected, ensure_ascii=False), inference_ms),
        )

    return {"inference_ms": inference_ms, "detected_items": detected}


# -------------------- INVENTARIO DE NEVERA (CRUD + Invalidación caché) --------------------

@app.get("/fridge/items", response_model=List[FridgeItemResponse])
def list_fridge_items(
    source: Optional[str] = Query(None, pattern="^(camera|manual|pantry)$"),
    current_user: dict = Depends(get_current_user),
):
    with get_db() as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM fridge_items WHERE user_id = ? AND source = ? ORDER BY updated_at DESC",
                (current_user["id"], source),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM fridge_items WHERE user_id = ? ORDER BY updated_at DESC",
                (current_user["id"],),
            ).fetchall()
    return [dict(r) for r in rows]


@app.post("/fridge/items", response_model=FridgeItemResponse, status_code=status.HTTP_201_CREATED)
def add_fridge_item(item: FridgeItemCreate, current_user: dict = Depends(get_current_user)):
    ing = item.ingredient_es.strip().lower()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM fridge_items WHERE user_id = ? AND ingredient_es = ?",
            (current_user["id"], ing),
        ).fetchone()
        if existing:
            new_qty = min(99, existing["quantity"] + item.quantity)
            conn.execute(
                "UPDATE fridge_items SET quantity = ?, source = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_qty, item.source, existing["id"]),
            )
            row = conn.execute("SELECT * FROM fridge_items WHERE id = ?", (existing["id"],)).fetchone()
        else:
            cur = conn.execute(
                "INSERT INTO fridge_items (user_id, ingredient_es, source, quantity) VALUES (?, ?, ?, ?)",
                (current_user["id"], ing, item.source, item.quantity),
            )
            row = conn.execute("SELECT * FROM fridge_items WHERE id = ?", (cur.lastrowid,)).fetchone()
    ml_engine.recommend_cache.clear()
    return dict(row)


@app.put("/fridge/items/{item_id}", response_model=FridgeItemResponse)
def update_fridge_item(
    item_id: int,
    payload: FridgeItemUpdate,
    current_user: dict = Depends(get_current_user),
):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM fridge_items WHERE id = ? AND user_id = ?",
            (item_id, current_user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Ingrediente no encontrado en tu nevera")

        new_ing = payload.ingredient_es.strip().lower() if payload.ingredient_es else row["ingredient_es"]
        new_src = payload.source if payload.source else row["source"]
        new_qty = payload.quantity if payload.quantity is not None else row["quantity"]

        conn.execute(
            "UPDATE fridge_items SET ingredient_es = ?, source = ?, quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_ing, new_src, new_qty, item_id),
        )
        updated = conn.execute("SELECT * FROM fridge_items WHERE id = ?", (item_id,)).fetchone()
    ml_engine.recommend_cache.clear()
    return dict(updated)


@app.delete("/fridge/items/{item_id}")
def delete_fridge_item(item_id: int, current_user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM fridge_items WHERE id = ? AND user_id = ?",
            (item_id, current_user["id"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Ingrediente no encontrado en tu nevera")
    ml_engine.recommend_cache.clear()
    return {"deleted": True, "item_id": item_id}


# -------------------- RECOMENDACIÓN DE RECETAS (TF-IDF + Coseno) --------------------

@app.post("/recommend", response_model=List[RecipeRecommendation])
def recommend_custom(
    req: RecommendationRequest,
    current_user: dict = Depends(get_current_user),
):
    return ml_engine.recommend(
        ingredients=req.ingredients,
        max_missing=req.max_missing,
        top_k=req.top_k,
        category=req.category,
    )


@app.get("/recommend/from-fridge", response_model=List[RecipeRecommendation])
def recommend_from_fridge(
    max_missing: int = Query(5, ge=0, le=10),
    top_k: int = Query(5, ge=1, le=20),
    category: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT ingredient_es FROM fridge_items WHERE user_id = ? AND source != 'pantry'",
            (current_user["id"],),
        ).fetchall()
    ingredients = [r["ingredient_es"] for r in rows]
    if not ingredients:
        raise HTTPException(
            status_code=400,
            detail="Tu nevera está vacía. Escanea o añade al menos un ingrediente primero.",
        )
    return ml_engine.recommend(
        ingredients=ingredients,
        max_missing=max_missing,
        top_k=top_k,
        category=category,
    )


@app.get("/recipes/{recipe_id}", response_model=RecipeDetailResponse)
def get_recipe_detail(recipe_id: int):
    detail = ml_engine.get_recipe_detail(recipe_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Receta no encontrada")
    return detail


# -------------------- RECETAS FAVORITAS --------------------

@app.get("/favorites", response_model=List[FavoriteResponse])
def list_favorites(current_user: dict = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM favorite_recipes WHERE user_id = ? ORDER BY saved_at DESC",
            (current_user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/favorites", response_model=FavoriteResponse, status_code=status.HTTP_201_CREATED)
def add_favorite(fav: FavoriteCreate, current_user: dict = Depends(get_current_user)):
    detail = ml_engine.get_recipe_detail(fav.recipe_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Receta no encontrada")

    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM favorite_recipes WHERE user_id = ? AND recipe_id = ?",
            (current_user["id"], fav.recipe_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE favorite_recipes SET notes = ?, saved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (fav.notes, existing["id"]),
            )
            row = conn.execute(
                "SELECT * FROM favorite_recipes WHERE id = ?", (existing["id"],)
            ).fetchone()
        else:
            cur = conn.execute(
                "INSERT INTO favorite_recipes (user_id, recipe_id, dish_title, notes) VALUES (?, ?, ?, ?)",
                (current_user["id"], fav.recipe_id, detail["title"], fav.notes),
            )
            row = conn.execute(
                "SELECT * FROM favorite_recipes WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
    return dict(row)


@app.delete("/favorites/{fav_id}")
def delete_favorite(fav_id: int, current_user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM favorite_recipes WHERE id = ? AND user_id = ?",
            (fav_id, current_user["id"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Favorito no encontrado")
    return {"deleted": True, "fav_id": fav_id}


# -------------------- TELEMETRÍA DE ESCANEOS (Para Dashboard) --------------------

@app.get("/scans/recent")
def list_recent_scans(
    limit: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, detected_json, inference_ms, created_at FROM scan_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (current_user["id"], limit),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "detected_items": json.loads(r["detected_json"]),
            "inference_ms": r["inference_ms"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# -------------------- ASISTENTE DE COCINA --------------------

@app.post("/assistant/chat", response_model=ChatResponse)
def assistant_chat(
    req: ChatRequest,
    current_user: dict = Depends(get_current_user)
):

    if req.messages[-1].role != "user":
        raise HTTPException(
            status_code=400,
            detail="El último mensaje debe ser del usuario."
        )

    # 1. Obtener el inventario real del usuario
    with get_db() as conn:

        rows = conn.execute(
            """
            SELECT ingredient_es, quantity, source
            FROM fridge_items
            WHERE user_id = ?
            """,
            (current_user["id"],)
        ).fetchall()

    inventory = [dict(row) for row in rows]

    ingredients = [
        item["ingredient_es"]
        for item in inventory
        if item["source"] != "pantry"
    ]

    # 2. Obtener recetas del recomendador existente
    recipes = []

    if ingredients:

        recommendations = ml_engine.recommend(
            ingredients=ingredients,
            max_missing=3,
            top_k=5,
            category=None
        )

        for recipe in recommendations:

            detail = ml_engine.get_recipe_detail(
                recipe["recipe_id"]
            ) or {}

            recipes.append({
                "title": recipe["title"],
                "category": recipe["category"],
                "match_pct": recipe["match_pct"],
                "matched_ingredients":
                    recipe["matched_ingredients"],
                "missing_ingredients":
                    recipe["missing_ingredients"],
                "raw_ingredients":
                    str(detail.get("raw_ingredients", ""))[:2000],
                "instructions":
                    str(recipe["instructions"])[:1500]
            })

    # 3. Preparar el historial de conversación
    messages = [
        message.model_dump()
        for message in req.messages
    ]

    # 4. Enviar la información a Ollama
    try:

        result = generate_chat_response(
            messages=messages,
            ingredients=inventory,
            recipes=recipes
        )

    except RuntimeError as exc:

        raise HTTPException(
            status_code=502,
            detail=str(exc)
        ) from exc

    # 5. Devolver la respuesta al frontend
    return {
        "answer": result["answer"],
        "model": result["model"],
        "response_time": result["response_time"],
        "ingredients_used": [
            item["ingredient_es"]
            for item in inventory
        ],
        "recipes_used": [
            recipe["title"]
            for recipe in recipes
        ]
    }
