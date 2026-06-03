# Адаптивное Обучение - Краткая Справка

## Что реализовано?
Система теперь может персонализировать диагностические задания на основе истории пользователя.

## Три ключевых параметра для персонализации

### 1. Общий уровень (estimated_level)
- Определяется по результатам прошлых diagnostic sessions
- CEFR уровень: A1, A2, B1, B2, C1
- Для новых пользователей: A2 по умолчанию

### 2. Прогрессия (trend + velocity)
- **improving** - точность растёт (velocity > +0.05)
- **stable** - точность стабильна
- **declining** - точность падает (velocity < -0.05)
- **insufficient_data** - мало данных (< 2 сессий)

### 3. Проблемные навыки (weak_areas)
- Subskills с accuracy < 60%
- Например: "verb_conjugation", "past_tense"
- Используется для формирования 60% заданий

## API для клиента

### Получить рекомендации
```http
GET /v1/learning/recommendations
X-User-ID: user_123

Ответ:
{
  "recommended_level": "B1",         // Следующий уровень
  "focus_areas": ["grammar", "..."], // Слабые места
  "study_plan": "maintain",          // advance/review/maintain
  "current_accuracy": 0.72,
  "trend": "improving"
}
```

### Запустить адаптивную диагностику
```http
POST /v1/learning/diagnostic/start
{
  "nativeLanguage": "ru",
  "targetLanguage": "en",
  "startLevelGuess": "A2",
  "useAdaptive": true  ⬅️ Включает персонализацию
}
```

## Логика работы

### Стандартный режим (useAdaptive=false)
```
load_blueprint_v0() → 25 заданий по start_level
```

### Адаптивный режим (useAdaptive=true)
```
1. get_user_learning_profile() → получить слабые места
2. load_blueprint_adaptive() → сформировать:
   - 60% заданий на weak_subskills
   - 40% стандартных заданий
```

## Функции в diagnostic_session.py

### get_user_learning_profile(db, user_id)
**Что делает:** Анализирует всю историю пользователя  
**Возвращает:**
- estimated_level: текущий CEFR
- weak_areas: список проблемных subskills
- avg_accuracy: средняя точность
- session_count: количество сессий

### load_blueprint_adaptive(db, user_id, ...)
**Что делает:** Генерирует персонализированный blueprint  
**Логика:**
- Если есть weak_areas → 60% на них, 40% обычные
- Если нет истории → fallback на load_blueprint_v0()

### analyze_user_progression(db, user_id)
**Что делает:** Отслеживает динамику  
**Возвращает:**
- trend: improving/stable/declining
- velocity: скорость изменения точности
- level_progression: история уровней
- accuracy_progression: история точности

### get_personalized_recommendations(db, user_id)
**Что делает:** Выдаёт рекомендации  
**Решения:**
```python
if avg_accuracy < 50%:
    recommended_level = current_level - 1
    study_plan = "review_basics"
elif avg_accuracy > 75% and trend == "improving":
    recommended_level = current_level + 1
    study_plan = "advance"
else:
    recommended_level = current_level
    study_plan = "maintain"
```

## Тестирование

### Unit тесты
```bash
pytest tests/test_adaptive_learning.py -v
# 6 passed in 0.35s ✅
```

### Integration тест
```powershell
.\test_recommendations_endpoint.ps1
# ✅ Recommendations endpoint test completed successfully!
```

## Примеры использования

### Сценарий 1: Новый пользователь
```
1. Первая диагностика: useAdaptive=false (нет истории)
2. GET /recommendations → "insufficient_data", level="A2"
3. Вторая диагностика: useAdaptive=true → fallback на стандартный (мало данных)
4. После 2-3 сессий → система начнёт адаптироваться
```

### Сценарий 2: Опытный пользователь с прогрессом
```
1. История: A2 (60%), A2 (68%), B1 (72%)
2. GET /recommendations →
   {
     "recommended_level": "B1",
     "trend": "improving",
     "focus_areas": ["verb_conjugation"],
     "study_plan": "maintain"
   }
3. Следующая диагностика: useAdaptive=true, level=B1
   → 60% заданий на verb_conjugation
```

### Сценарий 3: Пользователь с падающей точностью
```
1. История: B1 (75%), B1 (68%), B1 (55%)
2. GET /recommendations →
   {
     "recommended_level": "A2",  ⬅️ Понижение
     "trend": "declining",
     "study_plan": "review_basics"
   }
```

## База данных
**Изменения:** НЕ ТРЕБУЮТСЯ  
**Используется:**
- diagnostic_sessions (user_id, status, created_at, finished_at)
- diagnostic_attempts (session_id, is_correct, score, tags_snapshot_json)
- diagnostic_session_items (session_id, tags_json)

## Обратная совместимость
✅ **Полная:** Все существующие клиенты работают без изменений  
✅ **useAdaptive опциональный:** По умолчанию false  
✅ **Fallback логика:** Если нет данных → стандартный режим

## Что дальше?
1. ✅ Инфраструктура готова
2. ✅ Тесты проходят
3. ✅ API работает
4. ✅ Docker образ обновлён

**Готово к продакшену!**

## Метрики для мониторинга
```
- adaptive_sessions_count: Количество adaptive сессий
- fallback_rate: % fallback на standard blueprint
- avg_weak_areas_per_user: Среднее количество слабых мест
- trend_distribution: Распределение improving/stable/declining
```

## Производительность
- Запрос профиля: O(n) по количеству сессий юзера
- Рекомендация: добавить индекс на (user_id, status, finished_at)
- Кэширование: Redis для часто запрашиваемых профилей
