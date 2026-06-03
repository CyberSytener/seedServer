"""
CV Processor with Versioning

Обработчик CV с полной поддержкой версионирования и отката изменений.
Позволяет создавать, редактировать и откатывать CV без потери данных.
"""

import uuid
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from copy import deepcopy

from .cv_contracts import (
    CVData,
    CVVersion,
    CVGenerationRequest,
    CVGenerationResponse,
    CVUpdateRequest,
    PersonalInfo,
    ProfessionalSummary,
    WorkExperience,
    Education,
    SkillCategory,
    ExperienceLevel
)


class CVVersionStore:
    """
    Хранилище версий CV.
    
    В продакшене заменить на PostgreSQL/Redis.
    Сейчас - in-memory для демонстрации.
    """
    
    def __init__(self):
        # user_id -> List[CVVersion]
        self._versions: Dict[str, List[CVVersion]] = {}
        # version_id -> CVVersion
        self._version_index: Dict[str, CVVersion] = {}
    
    async def save_version(self, version: CVVersion) -> None:
        """Сохранить новую версию."""
        user_id = version.created_by
        
        if user_id not in self._versions:
            self._versions[user_id] = []
        
        # Если это новая текущая версия, снять флаг у предыдущей
        if version.is_current:
            for v in self._versions[user_id]:
                v.is_current = False
        
        self._versions[user_id].append(version)
        self._version_index[version.version_id] = version
    
    async def get_version(self, version_id: str) -> Optional[CVVersion]:
        """Получить версию по ID."""
        return self._version_index.get(version_id)
    
    async def get_user_versions(
        self,
        user_id: str,
        limit: int = 50
    ) -> List[CVVersion]:
        """Получить все версии пользователя."""
        versions = self._versions.get(user_id, [])
        # Отсортировать от новых к старым
        return sorted(versions, key=lambda v: v.created_at, reverse=True)[:limit]
    
    async def get_current_version(self, user_id: str) -> Optional[CVVersion]:
        """Получить текущую версию пользователя."""
        versions = self._versions.get(user_id, [])
        for v in versions:
            if v.is_current:
                return v
        return None
    
    async def get_version_history(
        self,
        version_id: str,
        max_depth: int = 10
    ) -> List[CVVersion]:
        """
        Получить историю версии (chain назад через parent_version_id).
        
        Returns: List от текущей до самой первой версии.
        """
        history = []
        current_id = version_id
        depth = 0
        
        while current_id and depth < max_depth:
            version = await self.get_version(current_id)
            if not version:
                break
            
            history.append(version)
            current_id = version.parent_version_id
            depth += 1
        
        return history


class CVProcessor:
    """
    Процессор для создания и управления CV.
    
    Основные функции:
    1. Генерация CV из user input (с помощью LLM)
    2. Версионирование и история изменений
    3. Применение правок
    4. Откат к предыдущей версии
    """
    
    def __init__(self, version_store: Optional[CVVersionStore] = None):
        self.version_store = version_store or CVVersionStore()
        self._generation_lock = asyncio.Lock()
    
    # ========================================================================
    # ГЕНЕРАЦИЯ CV
    # ========================================================================
    
    async def generate_cv(
        self,
        request: CVGenerationRequest
    ) -> CVGenerationResponse:
        """
        Генерация CV из пользовательского ввода.
        
        Основной flow:
        1. Парсинг user_input с помощью LLM
        2. Извлечение структурированных данных
        3. Создание CVData
        4. Сохранение как новая версия
        5. Валидация и расчет completeness_score
        """
        async with self._generation_lock:
            # 1. Парсинг user input -> структурированные данные
            cv_data = await self._parse_user_input(
                request.user_input,
                request.configuration
            )
            
            # 2. Если есть existing_data - мержим
            if request.existing_data:
                cv_data = await self._merge_cv_data(
                    request.existing_data,
                    cv_data
                )
            
            # 3. Валидация
            validation_result = await self._validate_cv_data(cv_data)
            
            # 4. Создание версии
            if request.base_version_id:
                base_version = await self.version_store.get_version(
                    request.base_version_id
                )
                parent_version_id = request.base_version_id
                
                # Получить номер версии
                history = await self.version_store.get_version_history(
                    request.base_version_id
                )
                version_number = len(history) + 1
            else:
                parent_version_id = None
                version_number = 1
            
            version = CVVersion(
                version_id=f"cv_{uuid.uuid4().hex[:12]}",
                version_number=version_number,
                cv_data=cv_data,
                created_by=request.user_id,
                change_description="Initial CV generation",
                parent_version_id=parent_version_id,
                is_current=True,
                is_finalized=False
            )
            
            # 5. Сохранить версию
            await self.version_store.save_version(version)
            
            # 6. Сформировать ответ
            return CVGenerationResponse(
                version_id=version.version_id,
                version_number=version.version_number,
                cv_data=cv_data,
                status="draft",
                pdf_generated=False,
                recommendations=validation_result.recommendations,
                completeness_score=validation_result.completeness_score,
                missing_sections=validation_result.missing_sections
            )
    
    async def _parse_user_input(
        self,
        user_input: str,
        configuration: Any
    ) -> CVData:
        """
        Парсинг user input с помощью LLM.
        
        TODO: Интеграция с LLM (GPT-4, Claude, Gemini).
        Сейчас - mock для демонстрации.
        """
        # Mock: простая эвристика для демонстрации
        # В продакшене здесь промпт в LLM с structured output
        
        lines = user_input.strip().split('\n')
        name_parts = []
        
        # Простой парсинг имени - ищем слова после "зовут" или большие буквы
        for line in lines:
            if 'зовут' in line.lower() or 'name' in line.lower():
                # Найти слова после "зовут"
                words = line.split()
                for i, word in enumerate(words):
                    if 'зовут' in word.lower() and i + 1 < len(words):
                        # Взять следующие 2 слова после "зовут"
                        potential_names = words[i+1:i+3]
                        name_parts = [w.strip('.,') for w in potential_names if w[0].isupper() and len(w) > 1]
                        break
                if name_parts:
                    break
        
        # Если не нашли через "зовут", ищем просто большие буквы подряд
        if not name_parts:
            for line in lines:
                words = line.split()
                caps_words = [w for w in words if w and w[0].isupper() and len(w) > 1 and w.isalpha()]
                if len(caps_words) >= 2:
                    name_parts = caps_words[:2]
                    break
        
        first_name = name_parts[0] if len(name_parts) > 0 else "Иван"
        last_name = name_parts[1] if len(name_parts) > 1 else "Иванов"
        
        # Парсинг опыта
        years_exp = 0
        for line in lines:
            if ('лет' in line.lower() or 'years' in line.lower() or 'года' in line.lower() or 'год' in line.lower()):
                words = line.split()
                for i, w in enumerate(words):
                    # Убрать знаки препинания и проверить
                    clean_w = w.strip('.,+-')
                    if clean_w.isdigit():
                        num = int(clean_w)
                        # Только если это разумный опыт (не год)
                        if num <= 50:
                            years_exp = num
                            break
        
        # Если не нашли опыт, но есть слово "разработчик" или "developer", ставим минимум 1 год
        if years_exp == 0:
            if 'разработчик' in user_input.lower() or 'developer' in user_input.lower():
                years_exp = 1
        
        # Парсинг технологий
        technologies = []
        tech_keywords = ['python', 'javascript', 'fastapi', 'react', 'postgresql', 'docker', 'aws', 'kubernetes', 'redis']
        input_lower = user_input.lower()
        for tech in tech_keywords:
            if tech in input_lower:
                technologies.append(tech.capitalize())
        
        # Построение CVData
        personal_info = PersonalInfo(
            first_name=first_name,
            last_name=last_name,
            email=f"{first_name.lower()}.{last_name.lower()}@example.com",
            phone="+7 999 123 4567"
        )
        
        experience_level = ExperienceLevel.JUNIOR
        if years_exp >= 10:
            experience_level = ExperienceLevel.LEAD
        elif years_exp >= 5:
            experience_level = ExperienceLevel.SENIOR
        elif years_exp >= 2:
            experience_level = ExperienceLevel.MIDDLE
        
        # Обеспечить минимум 3 навыка, максимум 10
        if not technologies:
            technologies = ["Programming", "Software Development", "Problem Solving"]
        elif len(technologies) < 3:
            # Добавить общие навыки только если их меньше 3
            while len(technologies) < 3:
                technologies.append("Software Development")
        
        # Ограничить до 10 навыков
        technologies = technologies[:10]
        
        professional_summary = ProfessionalSummary(
            title="Software Developer",
            summary=f"Experienced developer with {years_exp} years in software engineering. Skilled in various technologies and frameworks.",
            years_of_experience=years_exp,
            experience_level=experience_level,
            key_skills=technologies
        )
        
        cv_data = CVData(
            configuration=configuration,
            personal_info=personal_info,
            professional_summary=professional_summary,
            work_experience=[],
            education=[],
            skills=[]
        )
        
        return cv_data
    
    async def _merge_cv_data(
        self,
        existing: CVData,
        new_data: CVData
    ) -> CVData:
        """Мерж существующих данных с новыми."""
        # Простой мерж - можно расширить логику
        merged = deepcopy(existing)
        
        # Обновить personal_info если есть новые данные
        if new_data.personal_info.phone != "+7 999 123 4567":  # не дефолт
            merged.personal_info = new_data.personal_info
        
        # Добавить новый опыт работы
        merged.work_experience.extend(new_data.work_experience)
        
        # Обновить summary если есть
        if new_data.professional_summary:
            merged.professional_summary = new_data.professional_summary
        
        return merged
    
    # ========================================================================
    # ОБНОВЛЕНИЕ CV
    # ========================================================================
    
    async def update_cv(
        self,
        request: CVUpdateRequest
    ) -> CVGenerationResponse:
        """
        Применение правок к CV.
        
        Flow:
        1. Получить базовую версию
        2. Применить изменения (updates)
        3. Создать новую версию (если create_new_version=True)
        4. Сохранить и вернуть результат
        """
        # 1. Получить версию
        base_version = await self.version_store.get_version(request.version_id)
        if not base_version:
            raise ValueError(f"Version {request.version_id} not found")
        
        # Проверка прав пользователя
        if base_version.created_by != request.user_id:
            raise PermissionError("User does not own this CV version")
        
        # 2. Применить изменения
        updated_cv_data = await self._apply_updates(
            base_version.cv_data,
            request.updates
        )
        
        # 3. Валидация
        validation_result = await self._validate_cv_data(updated_cv_data)
        
        # 4. Создать новую версию или обновить существующую
        if request.create_new_version:
            # Новая версия
            new_version = CVVersion(
                version_id=f"cv_{uuid.uuid4().hex[:12]}",
                version_number=base_version.version_number + 1,
                cv_data=updated_cv_data,
                created_by=request.user_id,
                change_description=request.change_description,
                parent_version_id=base_version.version_id,
                is_current=True,
                is_finalized=False
            )
            
            await self.version_store.save_version(new_version)
            
            return CVGenerationResponse(
                version_id=new_version.version_id,
                version_number=new_version.version_number,
                cv_data=updated_cv_data,
                status="draft",
                pdf_generated=False,
                recommendations=validation_result.recommendations,
                completeness_score=validation_result.completeness_score,
                missing_sections=validation_result.missing_sections
            )
        else:
            # Обновить существующую версию (если не финализирована)
            if base_version.is_finalized:
                raise ValueError("Cannot update finalized version")
            
            base_version.cv_data = updated_cv_data
            base_version.change_description = request.change_description
            
            return CVGenerationResponse(
                version_id=base_version.version_id,
                version_number=base_version.version_number,
                cv_data=updated_cv_data,
                status="draft",
                pdf_generated=False,
                recommendations=validation_result.recommendations,
                completeness_score=validation_result.completeness_score,
                missing_sections=validation_result.missing_sections
            )
    
    async def _apply_updates(
        self,
        cv_data: CVData,
        updates: Dict[str, Any]
    ) -> CVData:
        """
        Применить частичные обновления к CVData.
        
        Поддерживает dot-notation и array indexing:
        - "personal_info.phone" -> обновить телефон
        - "work_experience[0].company" -> обновить компанию первого опыта
        """
        # Создать копию для изменений
        updated = deepcopy(cv_data)
        
        for path, value in updates.items():
            self._set_nested_value(updated, path, value)
        
        return updated
    
    def _set_nested_value(self, obj: Any, path: str, value: Any) -> None:
        """Установить значение по вложенному пути."""
        from app.core.realtime.optimized.cv_contracts import (
            WorkExperience, Education, SkillCategory, Certification, Language
        )
        
        parts = path.split('.')
        current = obj
        
        for i, part in enumerate(parts[:-1]):
            # Проверка на array indexing
            if '[' in part and ']' in part:
                field_name, index_str = part.split('[')
                index = int(index_str.rstrip(']'))
                
                current = getattr(current, field_name)[index]
            else:
                current = getattr(current, part)
        
        # Последний элемент - установить значение
        last_part = parts[-1]
        if '[' in last_part and ']' in last_part:
            field_name, index_str = last_part.split('[')
            index = int(index_str.rstrip(']'))
            getattr(current, field_name)[index] = value
        else:
            # Если это list и значение - list of dicts, преобразовать в модели
            if isinstance(value, list):
                field_info = current.model_fields.get(last_part)
                if field_info:
                    # Проверить тип - это list моделей?
                    type_hint = field_info.annotation
                    if 'List' in str(type_hint) or 'list' in str(type_hint):
                        # Попытаться распаковать
                        converted = []
                        for item in value:
                            if isinstance(item, dict):
                                # Определить тип модели
                                if last_part == 'work_experience':
                                    converted.append(WorkExperience(**item))
                                elif last_part == 'education':
                                    converted.append(Education(**item))
                                elif last_part == 'skills':
                                    converted.append(SkillCategory(**item))
                                elif last_part == 'certifications':
                                    converted.append(Certification(**item))
                                elif last_part == 'languages':
                                    converted.append(Language(**item))
                                else:
                                    converted.append(item)
                            else:
                                converted.append(item)
                        setattr(current, last_part, converted)
                        return
            
            setattr(current, last_part, value)
    
    # ========================================================================
    # ОТКАТ ВЕРСИИ
    # ========================================================================
    
    async def rollback_to_version(
        self,
        user_id: str,
        target_version_id: str
    ) -> CVGenerationResponse:
        """
        Откат к предыдущей версии.
        
        Создает новую версию с данными из target_version.
        История сохраняется полностью.
        """
        # 1. Получить целевую версию
        target_version = await self.version_store.get_version(target_version_id)
        if not target_version:
            raise ValueError(f"Version {target_version_id} not found")
        
        # Проверка прав
        if target_version.created_by != user_id:
            raise PermissionError("User does not own this CV version")
        
        # 2. Получить текущую версию
        current_version = await self.version_store.get_current_version(user_id)
        
        # 3. Создать новую версию на основе target
        rollback_version = CVVersion(
            version_id=f"cv_{uuid.uuid4().hex[:12]}",
            version_number=(
                current_version.version_number + 1
                if current_version
                else 1
            ),
            cv_data=deepcopy(target_version.cv_data),
            created_by=user_id,
            change_description=f"Rollback to version {target_version.version_number}",
            parent_version_id=current_version.version_id if current_version else None,
            is_current=True,
            is_finalized=False
        )
        
        # 4. Сохранить
        await self.version_store.save_version(rollback_version)
        
        # 5. Валидация
        validation_result = await self._validate_cv_data(rollback_version.cv_data)
        
        return CVGenerationResponse(
            version_id=rollback_version.version_id,
            version_number=rollback_version.version_number,
            cv_data=rollback_version.cv_data,
            status="draft",
            pdf_generated=False,
            recommendations=validation_result.recommendations,
            completeness_score=validation_result.completeness_score,
            missing_sections=validation_result.missing_sections
        )
    
    async def get_version_diff(
        self,
        version_id_1: str,
        version_id_2: str
    ) -> Dict[str, Any]:
        """
        Получить diff между двумя версиями.
        
        Returns: Dict с изменениями.
        """
        v1 = await self.version_store.get_version(version_id_1)
        v2 = await self.version_store.get_version(version_id_2)
        
        if not v1 or not v2:
            raise ValueError("One or both versions not found")
        
        # Простой diff (можно улучшить)
        return {
            "version_1": {
                "id": v1.version_id,
                "number": v1.version_number,
                "created_at": v1.created_at.isoformat()
            },
            "version_2": {
                "id": v2.version_id,
                "number": v2.version_number,
                "created_at": v2.created_at.isoformat()
            },
            "changes": self._compute_diff(
                v1.cv_data.model_dump(),
                v2.cv_data.model_dump()
            )
        }
    
    def _compute_diff(self, dict1: Dict, dict2: Dict, path: str = "") -> List[Dict]:
        """Вычислить разницу между двумя словарями."""
        changes = []
        
        all_keys = set(dict1.keys()) | set(dict2.keys())
        
        for key in all_keys:
            current_path = f"{path}.{key}" if path else key
            
            if key not in dict1:
                changes.append({
                    "type": "added",
                    "path": current_path,
                    "value": dict2[key]
                })
            elif key not in dict2:
                changes.append({
                    "type": "removed",
                    "path": current_path,
                    "value": dict1[key]
                })
            elif dict1[key] != dict2[key]:
                if isinstance(dict1[key], dict) and isinstance(dict2[key], dict):
                    # Рекурсия для вложенных объектов
                    changes.extend(self._compute_diff(dict1[key], dict2[key], current_path))
                else:
                    changes.append({
                        "type": "modified",
                        "path": current_path,
                        "old_value": dict1[key],
                        "new_value": dict2[key]
                    })
        
        return changes
    
    # ========================================================================
    # ВАЛИДАЦИЯ
    # ========================================================================
    
    async def _validate_cv_data(self, cv_data: CVData) -> Any:
        """
        Валидация CV данных и расчет completeness score.
        
        Returns: ValidationResult с recommendations и score.
        """
        from dataclasses import dataclass
        
        @dataclass
        class ValidationResult:
            completeness_score: float
            missing_sections: List[str]
            recommendations: List[str]
        
        missing = []
        recommendations = []
        score = 0.0
        
        # Проверка обязательных секций
        if not cv_data.professional_summary:
            missing.append("professional_summary")
            recommendations.append("Добавьте профессиональное резюме")
        else:
            score += 0.2
        
        if not cv_data.work_experience:
            missing.append("work_experience")
            recommendations.append("Добавьте опыт работы")
        else:
            score += 0.3
            
            # Проверка достижений
            for exp in cv_data.work_experience:
                if not exp.achievements:
                    recommendations.append(
                        f"Добавьте конкретные достижения для позиции {exp.position}"
                    )
        
        if not cv_data.education:
            missing.append("education")
            recommendations.append("Добавьте информацию об образовании")
        else:
            score += 0.2
        
        if not cv_data.skills:
            missing.append("skills")
            recommendations.append("Добавьте навыки")
        else:
            score += 0.15
        
        # Фотография
        if cv_data.configuration.include_photo:
            if not cv_data.personal_info.photo_url:
                recommendations.append("Рекомендуем загрузить профессиональную фотографию")
            else:
                score += 0.1
                if not cv_data.personal_info.photo_enhanced:
                    recommendations.append("Можете улучшить фотографию с помощью AI")
        
        # Контакты
        if cv_data.personal_info.linkedin or cv_data.personal_info.github:
            score += 0.05
        else:
            recommendations.append("Добавьте ссылки на LinkedIn или GitHub")
        
        return ValidationResult(
            completeness_score=min(score, 1.0),
            missing_sections=missing,
            recommendations=recommendations
        )

