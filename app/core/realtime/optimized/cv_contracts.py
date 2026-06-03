"""
CV Data Contracts

Строгие Pydantic v2 контракты для создания CV.
Определяет структуру пользовательской информации, формат CV, и требования к каждой секции.
"""

from typing import Annotated, Optional, List, Dict, Any, Literal
from datetime import datetime, date, timezone
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from enum import Enum


# ============================================================================
# ENUMS
# ============================================================================

class CVStyle(str, Enum):
    """Стиль оформления CV."""
    PROFESSIONAL = "professional"  # Классический корпоративный
    MODERN = "modern"              # Современный минималистичный
    CREATIVE = "creative"          # Креативный для дизайнеров
    ACADEMIC = "academic"          # Академический для науки
    TECHNICAL = "technical"        # Технический для инженеров


class CVLength(str, Enum):
    """Длина CV."""
    ONE_PAGE = "one_page"          # 1 страница (краткое)
    TWO_PAGES = "two_pages"        # 2 страницы (стандарт)
    EXTENDED = "extended"          # 3+ страницы (детальное)


class ExperienceLevel(str, Enum):
    """Уровень опыта."""
    JUNIOR = "junior"              # 0-2 года
    MIDDLE = "middle"              # 2-5 лет
    SENIOR = "senior"              # 5-10 лет
    LEAD = "lead"                  # 10+ лет
    EXECUTIVE = "executive"        # C-level


class PhotoStyle(str, Enum):
    """Стиль обработки фотографии."""
    NATURAL = "natural"            # Естественная ретушь
    PROFESSIONAL = "professional"  # Профессиональная студийная
    CORPORATE = "corporate"        # Корпоративный стиль
    LINKEDIN = "linkedin"          # LinkedIn-стиль
    NONE = "none"                  # Без фото


# ============================================================================
# PHOTO REQUIREMENTS
# ============================================================================

class PhotoRequirements(BaseModel):
    """Требования к фотографии для CV."""
    
    # Размеры
    min_width: int = Field(200, description="Минимальная ширина в пикселях")
    min_height: int = Field(200, description="Минимальная высота в пикселях")
    max_width: int = Field(2000, description="Максимальная ширина в пикселях")
    max_height: int = Field(2000, description="Максимальная высота в пикселях")
    
    # Рекомендации
    recommended_width: int = Field(400, description="Рекомендуемая ширина")
    recommended_height: int = Field(400, description="Рекомендуемая высота")
    aspect_ratio: str = Field("1:1", description="Соотношение сторон")
    
    # Формат
    allowed_formats: List[str] = Field(
        default=["jpg", "jpeg", "png"],
        description="Допустимые форматы"
    )
    max_file_size_mb: float = Field(5.0, description="Максимальный размер файла")
    
    # AI Enhancement
    ai_enhancement_available: bool = Field(
        True,
        description="Доступно AI-улучшение"
    )
    enhancement_features: List[str] = Field(
        default=[
            "background_removal",      # Удаление фона
            "lighting_adjustment",     # Коррекция освещения
            "color_correction",        # Цветокоррекция
            "skin_smoothing",          # Сглаживание кожи
            "professional_background", # Профессиональный фон
        ],
        description="Доступные улучшения"
    )


# ============================================================================
# PERSONAL INFORMATION
# ============================================================================

class PersonalInfo(BaseModel):
    """Персональная информация."""
    
    # Обязательные поля
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=100, description="Email address")
    phone: str = Field(..., min_length=5, max_length=20)
    
    # Опциональные поля
    middle_name: Optional[str] = Field(None, max_length=100)
    date_of_birth: Optional[date] = None
    location: Optional[str] = Field(None, max_length=200, description="Город, страна")
    
    # Ссылки
    linkedin: Optional[HttpUrl] = None
    github: Optional[HttpUrl] = None
    portfolio: Optional[HttpUrl] = None
    website: Optional[HttpUrl] = None
    
    # Фотография
    photo_url: Optional[str] = Field(None, description="URL загруженной фотографии")
    photo_enhanced: bool = Field(False, description="Фото улучшено AI")
    photo_style: PhotoStyle = Field(PhotoStyle.PROFESSIONAL)
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "first_name": "Иван",
            "last_name": "Петров",
            "email": "ivan.petrov@example.com",
            "phone": "+7 (999) 123-45-67",
            "location": "Москва, Россия",
            "linkedin": "https://linkedin.com/in/ivanpetrov",
            "github": "https://github.com/ivanpetrov",
        }
    })


# ============================================================================
# PROFESSIONAL SUMMARY
# ============================================================================

class ProfessionalSummary(BaseModel):
    """Профессиональное резюме (краткая выжимка)."""
    
    title: str = Field(
        ...,
        min_length=5,
        max_length=100,
        description="Должность/звание (напр. 'Senior Python Developer')"
    )
    
    summary: str = Field(
        ...,
        min_length=50,
        max_length=500,
        description="Краткое профессиональное резюме (2-3 предложения)"
    )
    
    years_of_experience: int = Field(..., ge=0, le=50, description="Лет опыта")
    experience_level: ExperienceLevel = Field(...)
    
    key_skills: Annotated[
        List[str],
        Field(min_length=3, max_length=10, description="Ключевые навыки (топ 3-10)")
    ]

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "title": "Senior Python Developer",
            "summary": "Experienced Python developer with 7+ years in backend development, specialized in FastAPI and microservices architecture. Proven track record of building scalable systems.",
            "years_of_experience": 7,
            "experience_level": "senior",
            "key_skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"]
        }
    })


# ============================================================================
# WORK EXPERIENCE
# ============================================================================

class WorkExperience(BaseModel):
    """Опыт работы."""
    
    company: str = Field(..., min_length=1, max_length=200)
    position: str = Field(..., min_length=1, max_length=200)
    
    start_date: date = Field(...)
    end_date: Optional[date] = Field(None, description="None если текущая работа")
    is_current: bool = Field(False, description="Текущая работа")
    
    location: Optional[str] = Field(None, max_length=200)
    
    description: str = Field(
        ...,
        min_length=20,
        max_length=2000,
        description="Описание обязанностей и достижений"
    )
    
    achievements: Annotated[
        List[str],
        Field(max_length=10, description="Конкретные достижения (с метриками)")
    ] = []

    technologies: Annotated[
        List[str],
        Field(max_length=20, description="Использованные технологии")
    ] = []
    
    @field_validator('end_date')
    @classmethod
    def validate_dates(cls, v, info):
        """Проверка что end_date > start_date."""
        if v and info.data.get('start_date'):
            if v < info.data['start_date']:
                raise ValueError('end_date должна быть позже start_date')
        return v
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "company": "TechCorp Inc.",
            "position": "Senior Python Developer",
            "start_date": "2020-01-01",
            "end_date": None,
            "is_current": True,
            "location": "Москва, Россия",
            "description": "Разработка и поддержка микросервисной архитектуры на Python/FastAPI",
            "achievements": [
                "Оптимизировал API, снизив latency на 60%",
                "Внедрил CI/CD pipeline, ускорив deployment в 3 раза",
                "Провел менторинг 5 junior разработчиков"
            ],
            "technologies": ["Python", "FastAPI", "PostgreSQL", "Docker", "Kubernetes"]
        }
    })


# ============================================================================
# EDUCATION
# ============================================================================

class Education(BaseModel):
    """Образование."""
    
    institution: str = Field(..., min_length=1, max_length=200, description="Университет/школа")
    degree: str = Field(..., min_length=1, max_length=200, description="Степень/специальность")
    field_of_study: Optional[str] = Field(None, max_length=200, description="Направление")
    
    start_date: date = Field(...)
    end_date: Optional[date] = Field(None, description="None если в процессе")
    is_current: bool = Field(False, description="В процессе обучения")
    
    gpa: Optional[float] = Field(None, ge=0.0, le=5.0, description="Средний балл")
    honors: Optional[str] = Field(None, max_length=200, description="Награды/отличия")
    
    description: Optional[str] = Field(None, max_length=1000, description="Дополнительно")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "institution": "МГУ им. М.В. Ломоносова",
            "degree": "Бакалавр",
            "field_of_study": "Прикладная математика и информатика",
            "start_date": "2013-09-01",
            "end_date": "2017-06-30",
            "gpa": 4.8,
            "honors": "Красный диплом"
        }
    })


# ============================================================================
# SKILLS
# ============================================================================

class SkillCategory(BaseModel):
    """Категория навыков."""
    
    category: str = Field(..., min_length=1, max_length=100, description="Категория (Languages, Frameworks, etc.)")
    skills: Annotated[
        List[str],
        Field(min_length=1, max_length=20, description="Навыки в категории")
    ]
    proficiency_level: Optional[Literal["beginner", "intermediate", "advanced", "expert"]] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "category": "Programming Languages",
            "skills": ["Python", "JavaScript", "TypeScript", "Go"],
            "proficiency_level": "expert"
        }
    })


# ============================================================================
# CERTIFICATIONS & LANGUAGES
# ============================================================================

class Certification(BaseModel):
    """Сертификат."""
    
    name: str = Field(..., min_length=1, max_length=200)
    issuer: str = Field(..., min_length=1, max_length=200, description="Организация-эмитент")
    issue_date: date = Field(...)
    expiry_date: Optional[date] = None
    credential_id: Optional[str] = Field(None, max_length=100)
    credential_url: Optional[HttpUrl] = None


class Language(BaseModel):
    """Язык."""
    
    language: str = Field(..., min_length=1, max_length=50)
    proficiency: Literal["basic", "intermediate", "advanced", "native"] = Field(...)


# ============================================================================
# CV CONFIGURATION
# ============================================================================

class CVConfiguration(BaseModel):
    """Конфигурация CV (формат, стиль, требования)."""
    
    # Стиль и формат
    style: CVStyle = Field(CVStyle.PROFESSIONAL, description="Стиль оформления")
    length: CVLength = Field(CVLength.TWO_PAGES, description="Целевая длина")
    
    # Секции (какие включить)
    include_photo: bool = Field(True, description="Включить фотографию")
    include_summary: bool = Field(True, description="Включить профессиональное резюме")
    include_experience: bool = Field(True, description="Включить опыт работы")
    include_education: bool = Field(True, description="Включить образование")
    include_skills: bool = Field(True, description="Включить навыки")
    include_certifications: bool = Field(False, description="Включить сертификаты")
    include_languages: bool = Field(False, description="Включить языки")
    include_projects: bool = Field(False, description="Включить проекты")
    
    # Опциональные секции
    custom_sections: List[str] = Field(
        default=[],
        description="Дополнительные кастомные секции"
    )
    
    # Требования к контенту
    max_experience_items: int = Field(5, ge=1, le=20, description="Макс. позиций в опыте")
    max_education_items: int = Field(3, ge=1, le=10, description="Макс. образований")
    max_achievements_per_job: int = Field(5, ge=1, le=10, description="Макс. достижений на работу")
    
    # Целевая позиция (для оптимизации контента)
    target_position: Optional[str] = Field(None, max_length=200, description="Целевая позиция")
    target_industry: Optional[str] = Field(None, max_length=100, description="Целевая индустрия")
    
    # Языковые настройки
    language: Literal["ru", "en"] = Field("ru", description="Язык CV")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "style": "professional",
            "length": "two_pages",
            "include_photo": True,
            "target_position": "Senior Python Developer",
            "target_industry": "FinTech",
            "language": "ru"
        }
    })


# ============================================================================
# COMPLETE CV DATA
# ============================================================================

class CVData(BaseModel):
    """Полные данные для создания CV."""
    
    # Конфигурация
    configuration: CVConfiguration = Field(...)
    
    # Основные данные
    personal_info: PersonalInfo = Field(...)
    professional_summary: Optional[ProfessionalSummary] = None
    
    # Опыт и образование
    work_experience: List[WorkExperience] = Field(default=[])
    education: List[Education] = Field(default=[])
    
    # Навыки
    skills: List[SkillCategory] = Field(default=[])
    
    # Дополнительно
    certifications: List[Certification] = Field(default=[])
    languages: List[Language] = Field(default=[])
    
    # Кастомные секции
    custom_sections: Dict[str, Any] = Field(
        default={},
        description="Дополнительные пользовательские секции"
    )
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "configuration": {
                "style": "professional",
                "length": "two_pages"
            },
            "personal_info": {
                "first_name": "Иван",
                "last_name": "Петров",
                "email": "ivan@example.com",
                "phone": "+7 999 123 4567"
            },
            "work_experience": [],
            "education": []
        }
    })


# ============================================================================
# CV VERSION (для версионирования)
# ============================================================================

class CVVersion(BaseModel):
    """Версия CV (для истории изменений)."""
    
    version_id: str = Field(..., description="Уникальный ID версии")
    version_number: int = Field(..., ge=1, description="Номер версии")
    
    cv_data: CVData = Field(..., description="Данные CV")
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(..., description="User ID")
    
    change_description: Optional[str] = Field(None, max_length=500, description="Описание изменений")
    parent_version_id: Optional[str] = Field(None, description="ID предыдущей версии")
    
    # Метаданные
    is_current: bool = Field(False, description="Текущая версия")
    is_finalized: bool = Field(False, description="Финализирована (PDF сгенерирован)")
    pdf_url: Optional[str] = Field(None, description="URL сгенерированного PDF")


# ============================================================================
# CV GENERATION REQUEST
# ============================================================================

class CVGenerationRequest(BaseModel):
    """Запрос на генерацию CV."""
    
    user_id: str = Field(..., description="ID пользователя")
    
    # Данные пользователя (краткая форма - snippet)
    user_input: str = Field(
        ...,
        min_length=50,
        max_length=5000,
        description="Пользовательский ввод (free-form text) о себе"
    )
    
    # Конфигурация
    configuration: CVConfiguration = Field(...)
    
    # Опциональные предзаполненные данные
    existing_data: Optional[CVData] = Field(None, description="Существующие данные для обновления")
    
    # Версионирование
    base_version_id: Optional[str] = Field(None, description="ID базовой версии для изменений")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "user_id": "user_123",
            "user_input": """
                Меня зовут Иван Петров. Работаю Python разработчиком 7 лет.
                Специализируюсь на backend разработке, FastAPI, микросервисах.
                Окончил МГУ по специальности прикладная математика.
                Сейчас работаю в TechCorp на позиции Senior Developer.
                Знаю Python, PostgreSQL, Docker, AWS. Есть опыт менторинга.
            """,
            "configuration": {
                "style": "professional",
                "length": "two_pages",
                "target_position": "Senior Python Developer"
            }
        }
    })


# ============================================================================
# CV GENERATION RESPONSE
# ============================================================================

class CVGenerationResponse(BaseModel):
    """Ответ на генерацию CV."""
    
    version_id: str = Field(..., description="ID созданной версии")
    version_number: int = Field(..., description="Номер версии")
    
    cv_data: CVData = Field(..., description="Сгенерированные данные CV")
    
    # Статус
    status: Literal["draft", "ready_for_review", "finalized"] = Field("draft")
    
    # PDF
    pdf_generated: bool = Field(False, description="PDF сгенерирован")
    pdf_url: Optional[str] = Field(None, description="URL PDF")
    
    # Рекомендации
    recommendations: List[str] = Field(
        default=[],
        description="Рекомендации по улучшению CV"
    )
    
    # Метрики
    completeness_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Оценка полноты CV (0-1)"
    )
    
    missing_sections: List[str] = Field(
        default=[],
        description="Отсутствующие важные секции"
    )
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "version_id": "v_abc123",
            "version_number": 1,
            "cv_data": {...},
            "status": "draft",
            "completeness_score": 0.85,
            "recommendations": [
                "Добавьте конкретные метрики в достижения",
                "Рекомендуем загрузить профессиональную фотографию"
            ]
        }
    })


# ============================================================================
# CV UPDATE REQUEST (для правок)
# ============================================================================

class CVUpdateRequest(BaseModel):
    """Запрос на обновление CV."""
    
    version_id: str = Field(..., description="ID версии для обновления")
    user_id: str = Field(..., description="ID пользователя")
    
    # Изменения
    updates: Dict[str, Any] = Field(
        ...,
        description="Partial updates (JsonPatch-style или simple dict)"
    )
    
    change_description: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Описание изменений"
    )
    
    # Создать новую версию или обновить текущую
    create_new_version: bool = Field(
        True,
        description="True - создать новую версию, False - обновить текущую"
    )
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "version_id": "v_abc123",
            "user_id": "user_123",
            "updates": {
                "personal_info.phone": "+7 999 888 7766",
                "work_experience[0].achievements": [
                    "Новое достижение с метриками"
                ]
            },
            "change_description": "Обновил телефон и добавил новое достижение",
            "create_new_version": True
        }
    })


# ============================================================================
# PHOTO ENHANCEMENT REQUEST
# ============================================================================

class PhotoEnhancementRequest(BaseModel):
    """Запрос на AI-улучшение фотографии."""
    
    user_id: str = Field(..., description="ID пользователя")
    photo_url: str = Field(..., description="URL исходной фотографии")
    
    style: PhotoStyle = Field(PhotoStyle.PROFESSIONAL, description="Стиль обработки")
    
    enhancements: List[str] = Field(
        default=["lighting_adjustment", "color_correction", "professional_background"],
        description="Какие улучшения применить"
    )
    
    # Настройки
    remove_background: bool = Field(True, description="Удалить фон")
    background_color: Optional[str] = Field("#FFFFFF", description="Цвет фона (hex)")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "user_id": "user_123",
            "photo_url": "https://example.com/photos/original.jpg",
            "style": "professional",
            "enhancements": ["lighting_adjustment", "skin_smoothing"],
            "remove_background": True
        }
    })


class PhotoEnhancementResponse(BaseModel):
    """Ответ на улучшение фотографии."""
    
    enhanced_photo_url: str = Field(..., description="URL улучшенного фото")
    original_photo_url: str = Field(..., description="URL оригинала")
    
    applied_enhancements: List[str] = Field(..., description="Примененные улучшения")
    
    processing_time_ms: float = Field(..., description="Время обработки")
    
    recommendations: List[str] = Field(
        default=[],
        description="Рекомендации по дальнейшему улучшению"
    )
