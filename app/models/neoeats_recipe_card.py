from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RecipeCardPenalty(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    points: int = Field(ge=0, le=100)


class RecipeCardMatchBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_coverage_pct: int = Field(ge=0, le=100)
    expiry_priority_pct: int = Field(ge=0, le=100)
    prefs_pct: int = Field(ge=0, le=100)
    constraints_pct: int = Field(ge=0, le=100)
    health_score_0_100: int = Field(default=0, ge=0, le=100)
    budget_fit_0_100: int = Field(default=0, ge=0, le=100)
    overall_score_0_100: int = Field(default=0, ge=0, le=100)
    penalties: List[RecipeCardPenalty] = Field(default_factory=list)


class RecipeCardIngredient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    quantity: float = Field(ge=0)
    unit: str
    source: str = Field(pattern="^(inventory|staple|missing)$")
    expires_at: Optional[str] = None
    days_to_expiry: Optional[int] = None
    is_estimate: bool = False


class RecipeCardMissingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    suggested_quantity: float = Field(ge=0)
    unit: str
    est_cost_nok: Optional[float] = Field(default=None, ge=0)


class RecipeCardNutrition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kcal_total: int = Field(ge=0)
    protein_g_total: float = Field(ge=0)
    protein_g_per_serving: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    per_serving: Optional[dict] = None
    estimate_confidence: str = Field(pattern="^(high|medium|low)$")


class RecipeCardProteinSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    approx_protein_per_100g: float = Field(ge=0)
    used_qty_g: float = Field(ge=0)


class RecipeCardProteinBadge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(pattern="^(High Protein|Protein Focus)$")
    protein_g_per_serving: float = Field(ge=0)
    main_sources: List[RecipeCardProteinSource] = Field(default_factory=list)
    score_0_100: Optional[int] = Field(default=None, ge=0, le=100)


class RecipeCardExpiryRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    days_to_expiry: int


class RecipeCardExpiryPriority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    used_first: List[RecipeCardExpiryRef] = Field(default_factory=list)
    soonest_days: Optional[int] = None


class RecipeCardActions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_cta: str = Field(pattern="^(start_cooking|order_missing)$")
    missing_cost_nok: Optional[float] = Field(default=None, ge=0)
    missing_count: int = Field(ge=0)


class RecipeCardCookingIngredientRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    quantity: float = Field(ge=0)
    unit: str


class RecipeCardCookingTimer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    duration_sec: int = Field(ge=0)


class RecipeCardCookingStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    title: str
    instruction: str
    duration_sec: Optional[int] = Field(default=None, ge=0)
    ingredients_used: List[RecipeCardCookingIngredientRef] = Field(default_factory=list)
    timers: List[RecipeCardCookingTimer] = Field(default_factory=list)
    tips: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class RecipeCardCookingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern="^cooking_plan_v1$")
    servings: int = Field(ge=1)
    steps: List[RecipeCardCookingStep] = Field(default_factory=list, min_length=3)


class RecipeCardV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="recipe_card_v1")
    recipe_id: str
    title: str
    match_pct: int = Field(ge=0, le=100)
    match_breakdown: RecipeCardMatchBreakdown
    ingredients: List[RecipeCardIngredient]
    missing_items: List[RecipeCardMissingItem]
    nutrition: RecipeCardNutrition
    protein_badge: Optional[RecipeCardProteinBadge] = None
    cooking_plan: Optional[RecipeCardCookingPlan] = None
    expiry_priority: RecipeCardExpiryPriority
    actions: RecipeCardActions
    missing_items_count: int = Field(default=0, ge=0)
    missing_cost_nok: Optional[int] = Field(default=None, ge=0)
    explain: str
    encoding_repaired: bool = False
    flags: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
