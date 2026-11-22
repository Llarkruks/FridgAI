from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)


class UserResponse(BaseModel):
    id: int
    username: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class IngredientRecognition(BaseModel):
    class_en: str
    ingredient_es: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: List[float] = Field(..., min_length=4, max_length=4)


class RecognitionResponse(BaseModel):
    inference_ms: float = Field(..., ge=0.0)
    detected_items: List[IngredientRecognition]


class FridgeItemCreate(BaseModel):
    ingredient_es: str = Field(..., min_length=2, max_length=50)
    source: str = Field("camera", pattern="^(camera|manual|pantry)$")
    quantity: int = Field(1, ge=1, le=99)


class FridgeItemUpdate(BaseModel):
    ingredient_es: Optional[str] = Field(None, min_length=2, max_length=50)
    source: Optional[str] = Field(None, pattern="^(camera|manual|pantry)$")
    quantity: Optional[int] = Field(None, ge=1, le=99)


class FridgeItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    ingredient_es: str
    source: str
    quantity: int
    updated_at: datetime


class RecommendationRequest(BaseModel):
    ingredients: List[str] = Field(..., min_length=1)
    pantry_basics: List[str] = Field(default_factory=list)
    max_missing: int = Field(5, ge=0, le=10)
    top_k: int = Field(5, ge=1, le=20)
    category: Optional[str] = None


class RecipeRecommendation(BaseModel):
    recipe_id: int
    title: str
    category: str
    match_pct: float = Field(..., ge=0.0, le=100.0)
    cosine_sim: float = Field(..., ge=0.0, le=1.0)
    score: float = Field(..., ge=0.0, le=1.0)
    matched_ingredients: List[str]
    missing_ingredients: List[str]
    instructions: str
    source_url: Optional[str] = None


class RecipeDetailResponse(BaseModel):
    recipe_id: int
    title: str
    category: str
    subcategory: Optional[str] = None
    raw_ingredients: str
    parsed_ingredients: List[str]
    parsed_pantry: List[str]
    instructions: str
    source_url: Optional[str] = None


class FavoriteCreate(BaseModel):
    recipe_id: int = Field(..., ge=0)
    notes: str = Field("", max_length=300)


class FavoriteResponse(BaseModel):
    id: int
    user_id: int
    recipe_id: int
    dish_title: str
    notes: str
    saved_at: datetime