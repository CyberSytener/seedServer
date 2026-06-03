# Course Modeling Feature Architecture

## Overview
Design document for the course modeling and generation feature, enabling automated course creation with structured lessons and diagnostic tasks based on educational taxonomies.

## Feature Summary

**User Story**: As an educator, I want to model complete courses with structured curricula, so that the system can automatically generate appropriate lessons and diagnostic tasks for each course component.

**Core Capability**: Generate multi-level courses (units → lessons → tasks) from high-level course descriptions, with automatic content generation for each component using LLM providers.

---

## Architecture Design

### 1. Data Model

#### Course Entity
```python
class Course(BaseModel):
    """Complete course with metadata and structure"""
    id: int
    title: str  # e.g., "English Grammar A1"
    description: str
    difficulty_level: str  # A1, A2, B1, B2, C1, C2
    estimated_hours: int  # Total course duration
    language: str  # Target language
    learning_objectives: list[str]
    prerequisites: list[str] = []
    created_by: int  # User ID
    created_at: datetime
    updated_at: datetime
```

#### CourseUnit (linking courses to units)
```python
class CourseUnit(BaseModel):
    """Unit within a course with sequencing"""
    id: int
    course_id: int
    unit_id: int  # Links to existing units table
    sequence_order: int  # Position in course (1, 2, 3...)
    weight: float = 1.0  # Importance/weight for progress calculation
    is_optional: bool = False
```

#### CourseEnrollment
```python
class CourseEnrollment(BaseModel):
    """User enrollment in a course"""
    id: int
    course_id: int
    user_id: int
    enrolled_at: datetime
    completed_at: Optional[datetime] = None
    progress_percentage: float = 0.0  # 0-100
    current_unit_id: Optional[int] = None
    last_activity: datetime
```

#### CourseLearningPath
```python
class CourseLearningPath(BaseModel):
    """Auto-generated learning path for course"""
    id: int
    course_id: int
    user_id: int
    path_data: dict  # Adaptive path JSON
    created_at: datetime
    updated_at: datetime
```

### 2. Database Schema

```sql
-- Courses table
CREATE TABLE courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    difficulty_level TEXT NOT NULL,  -- A1, A2, B1, B2, C1, C2
    estimated_hours INTEGER,
    language TEXT NOT NULL DEFAULT 'en',
    learning_objectives TEXT,  -- JSON array
    prerequisites TEXT,  -- JSON array
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    FOREIGN KEY (created_by) REFERENCES users(id)
);

-- Course units (many-to-many with sequencing)
CREATE TABLE course_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    unit_id INTEGER NOT NULL,
    sequence_order INTEGER NOT NULL,
    weight REAL DEFAULT 1.0,
    is_optional INTEGER DEFAULT 0,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
    FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE CASCADE,
    UNIQUE(course_id, unit_id),
    UNIQUE(course_id, sequence_order)
);

-- Course enrollments
CREATE TABLE course_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    enrolled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    progress_percentage REAL DEFAULT 0.0,
    current_unit_id INTEGER,
    last_activity TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (current_unit_id) REFERENCES units(id),
    UNIQUE(course_id, user_id)
);

-- Course learning paths (adaptive)
CREATE TABLE course_learning_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    path_data TEXT NOT NULL,  -- JSON
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(course_id, user_id)
);

-- Indexes for performance
CREATE INDEX idx_courses_created_by ON courses(created_by);
CREATE INDEX idx_courses_difficulty ON courses(difficulty_level);
CREATE INDEX idx_course_units_course ON course_units(course_id);
CREATE INDEX idx_course_units_unit ON course_units(unit_id);
CREATE INDEX idx_enrollments_user ON course_enrollments(user_id);
CREATE INDEX idx_enrollments_course ON course_enrollments(course_id);
CREATE INDEX idx_learning_paths_user ON course_learning_paths(user_id);
```

### 3. API Endpoints

#### Course Management

**Create Course**
```
POST /v1/courses
Authorization: Bearer <api_key>
Content-Type: application/json

{
  "title": "English Grammar Fundamentals",
  "description": "Complete A1-level grammar course",
  "difficulty_level": "A1",
  "estimated_hours": 40,
  "language": "en",
  "learning_objectives": [
    "Master present simple tense",
    "Use common prepositions correctly",
    "Form basic questions and negations"
  ],
  "prerequisites": [],
  "auto_generate": true  // Trigger course generation
}

Response: 201 Created
{
  "course_id": 123,
  "title": "English Grammar Fundamentals",
  "status": "generating",
  "job_id": "course_gen_abc123",
  "units_planned": 8
}
```

**Get Course**
```
GET /v1/courses/{course_id}
Authorization: Bearer <api_key>

Response: 200 OK
{
  "id": 123,
  "title": "English Grammar Fundamentals",
  "description": "...",
  "difficulty_level": "A1",
  "estimated_hours": 40,
  "units": [
    {
      "unit_id": 45,
      "title": "Present Simple Tense",
      "sequence_order": 1,
      "lesson_count": 5,
      "diagnostic_count": 3
    },
    ...
  ],
  "total_units": 8,
  "total_lessons": 40,
  "enrollment_count": 15
}
```

**List Courses**
```
GET /v1/courses?difficulty=A1&language=en&limit=20&offset=0
Authorization: Bearer <api_key>

Response: 200 OK
{
  "courses": [...],
  "total": 45,
  "limit": 20,
  "offset": 0
}
```

**Update Course**
```
PATCH /v1/courses/{course_id}
Authorization: Bearer <api_key>

{
  "title": "Updated Title",
  "description": "Updated description"
}
```

**Delete Course**
```
DELETE /v1/courses/{course_id}
Authorization: Bearer <admin_key>

Response: 204 No Content
```

#### Course Enrollment

**Enroll User**
```
POST /v1/courses/{course_id}/enroll
Authorization: Bearer <api_key>

Response: 200 OK
{
  "enrollment_id": 789,
  "course_id": 123,
  "user_id": 456,
  "enrolled_at": "2026-01-12T14:00:00Z",
  "starting_unit": {
    "unit_id": 45,
    "title": "Present Simple Tense"
  }
}
```

**Get Enrollment Progress**
```
GET /v1/courses/{course_id}/progress
Authorization: Bearer <api_key>

Response: 200 OK
{
  "course_id": 123,
  "user_id": 456,
  "progress_percentage": 35.5,
  "units_completed": 3,
  "units_total": 8,
  "current_unit": {
    "unit_id": 46,
    "title": "Past Simple Tense",
    "progress": 0.5
  },
  "last_activity": "2026-01-12T13:45:00Z",
  "estimated_completion": "2026-02-15T00:00:00Z"
}
```

#### Course Generation

**Generate Course Content**
```
POST /v1/courses/{course_id}/generate
Authorization: Bearer <admin_key>
Content-Type: application/json

{
  "generate_units": true,
  "generate_lessons": true,
  "generate_diagnostics": true,
  "units_config": [
    {
      "title": "Present Simple Tense",
      "topics": ["affirmative", "negative", "questions"],
      "lessons_per_topic": 2
    },
    ...
  ]
}

Response: 202 Accepted
{
  "job_id": "course_gen_xyz789",
  "status": "queued",
  "estimated_time_minutes": 15,
  "operations": {
    "units_to_create": 8,
    "lessons_to_generate": 40,
    "diagnostics_to_generate": 24
  }
}
```

**Check Generation Status**
```
GET /v1/jobs/{job_id}
Authorization: Bearer <api_key>

Response: 200 OK
{
  "id": "course_gen_xyz789",
  "status": "running",
  "progress": {
    "units_created": 5,
    "units_total": 8,
    "lessons_generated": 25,
    "lessons_total": 40
  },
  "eta_minutes": 8
}
```

### 4. Course Generation Engine

#### Generation Pipeline

```python
class CourseGenerationEngine:
    """Generate complete course content from course model"""
    
    async def generate_course(
        self,
        course: Course,
        config: CourseGenerationConfig
    ) -> CourseGenerationResult:
        """
        Generate complete course with units, lessons, and diagnostics.
        
        Pipeline:
        1. Analyze course objectives and difficulty
        2. Generate unit structure (topics, sequencing)
        3. For each unit:
           a. Generate lesson plan
           b. Generate individual lessons
           c. Generate diagnostic tasks
        4. Create learning path template
        5. Save to database
        
        Uses job queue for long-running generation.
        """
        
        # Step 1: Generate unit structure
        units = await self._generate_unit_structure(course)
        
        # Step 2: Generate content for each unit
        for unit in units:
            # Create unit in DB
            unit_id = await self._create_unit(unit)
            
            # Generate lessons for unit
            lessons = await self._generate_unit_lessons(
                course, unit, config.lessons_per_unit
            )
            
            # Generate diagnostics for unit
            diagnostics = await self._generate_unit_diagnostics(
                course, unit, config.diagnostics_per_unit
            )
            
            # Link to course
            await self._link_unit_to_course(course.id, unit_id)
        
        # Step 3: Generate adaptive learning path template
        await self._generate_learning_path_template(course)
        
        return CourseGenerationResult(
            course_id=course.id,
            units_created=len(units),
            lessons_generated=sum(len(u.lessons) for u in units),
            diagnostics_generated=sum(len(u.diagnostics) for u in units)
        )
    
    async def _generate_unit_structure(self, course: Course) -> list[UnitPlan]:
        """Generate high-level unit structure from course objectives"""
        
        prompt = f"""
        Create a structured curriculum for this course:
        
        Title: {course.title}
        Level: {course.difficulty_level}
        Objectives: {', '.join(course.learning_objectives)}
        Duration: {course.estimated_hours} hours
        
        Generate 6-10 units that:
        1. Progress logically from basics to advanced
        2. Cover all learning objectives
        3. Build on each other appropriately
        4. Align with {course.difficulty_level} CEFR level
        
        For each unit provide:
        - Title
        - Description
        - Topics covered (3-5 specific topics)
        - Prerequisites
        - Estimated hours
        
        Return as JSON array.
        """
        
        response = await self.llm_client.generate(
            system_prompt="You are an expert curriculum designer.",
            user_prompt=prompt,
            provider="gemini",
            max_tokens=4000
        )
        
        return self._parse_unit_structure(response.text)
    
    async def _generate_unit_lessons(
        self, course: Course, unit: UnitPlan, count: int
    ) -> list[Lesson]:
        """Generate lessons for a specific unit"""
        
        lessons = []
        for topic in unit.topics:
            lesson_prompt = f"""
            Create a lesson for:
            Course: {course.title} ({course.difficulty_level})
            Unit: {unit.title}
            Topic: {topic}
            
            Generate:
            1. Lesson title
            2. Learning objectives (3-4)
            3. Explanation content (500-800 words)
            4. Examples (5-7)
            5. Practice exercises (5)
            6. Review questions (3)
            
            Format as JSON.
            """
            
            response = await self.llm_client.generate(
                system_prompt="You are an expert language teacher.",
                user_prompt=lesson_prompt,
                provider="gemini"
            )
            
            lesson = self._parse_lesson(response.text)
            lessons.append(lesson)
        
        return lessons
    
    async def _generate_unit_diagnostics(
        self, course: Course, unit: UnitPlan, count: int
    ) -> list[Diagnostic]:
        """Generate diagnostic tasks for unit assessment"""
        
        diagnostics = []
        for i in range(count):
            diag_prompt = f"""
            Create diagnostic test {i+1} for:
            Course: {course.title}
            Unit: {unit.title}
            Topics: {', '.join(unit.topics)}
            
            Generate:
            1. Task type (fill-blank, multiple-choice, correction)
            2. Instructions
            3. Content/question
            4. Correct answer
            5. Distractor answers (if multiple-choice)
            6. Explanation
            
            Difficulty: {course.difficulty_level}
            Format as JSON.
            """
            
            response = await self.llm_client.generate(
                system_prompt="You are an expert test designer.",
                user_prompt=diag_prompt,
                provider="gemini"
            )
            
            diagnostic = self._parse_diagnostic(response.text)
            diagnostics.append(diagnostic)
        
        return diagnostics
```

### 5. Integration Points

#### Existing Systems
- **Learning Path System**: Course-based paths use course structure
- **Lesson Engine**: Generated lessons use existing lesson API
- **Diagnostic Engine**: Generated diagnostics use existing diagnostic API
- **Job Queue**: Course generation runs as background jobs
- **Progress Tracking**: Course progress builds on unit/lesson tracking

#### New Dependencies
- **CEFR Taxonomy**: Use existing `data/cefr_taxonomy.json`
- **LLM Router**: Use Gemini for generation (primary)
- **Prompt Templates**: New prompts for course/unit/lesson generation

---

## Implementation Plan

### Phase 1: Data Layer (Week 1)
- [ ] Create database schema (courses, course_units, enrollments)
- [ ] Write Alembic migration
- [ ] Add Pydantic models
- [ ] Create CRUD operations

### Phase 2: Basic API (Week 2)
- [ ] Implement course management endpoints (CRUD)
- [ ] Implement enrollment endpoints
- [ ] Add course listing and filtering
- [ ] Write integration tests

### Phase 3: Generation Engine (Week 3-4)
- [ ] Design course generation prompts
- [ ] Implement unit structure generation
- [ ] Implement lesson generation pipeline
- [ ] Implement diagnostic generation pipeline
- [ ] Add job queue integration

### Phase 4: Learning Path Integration (Week 5)
- [ ] Generate course-based learning paths
- [ ] Update progress tracking for courses
- [ ] Implement course completion logic
- [ ] Add analytics and reporting

### Phase 5: Polish & Production (Week 6)
- [ ] Add admin UI for course management
- [ ] Performance optimization (caching, batching)
- [ ] Documentation and examples
- [ ] Load testing and security review

---

## Configuration

### Environment Variables
```bash
# Course generation settings
SEED_COURSE_GENERATION_ENABLED=true
SEED_COURSE_DEFAULT_UNITS=8
SEED_COURSE_LESSONS_PER_UNIT=5
SEED_COURSE_DIAGNOSTICS_PER_UNIT=3
SEED_COURSE_GENERATION_PROVIDER=gemini
SEED_COURSE_GENERATION_MODEL=gemini-1.5-pro
```

### Feature Flags
```python
# Use existing feature flags system
await feature_flags.create_flag(
    name="course_modeling",
    enabled=False,  # Gradual rollout
    strategy=RolloutStrategy.PERCENTAGE,
    config={"percentage": 10},  # 10% of users
    description="Enable course modeling and generation"
)
```

---

## Testing Strategy

### Unit Tests
- Course CRUD operations
- Enrollment logic
- Progress calculation
- Generation prompt construction

### Integration Tests
- End-to-end course creation
- Course generation pipeline
- Learning path integration
- Progress tracking across courses

### Load Tests
- Course generation performance (10 courses in parallel)
- Enrollment at scale (1000 users)
- Progress tracking queries
- API endpoint performance

---

## Monitoring & Metrics

### Key Metrics
```
# Course operations
course_created_total
course_generation_duration_seconds
course_generation_errors_total

# Enrollments
course_enrollments_total
course_completions_total
course_dropout_rate

# Generation metrics
units_generated_total
lessons_generated_total
diagnostics_generated_total
generation_tokens_used_total
generation_cost_usd_total
```

### Alerts
- Course generation failure rate > 5%
- Generation time > 30 minutes
- LLM API errors during generation
- Database constraints violated

---

## Security Considerations

1. **Authorization**: Only admins can create/delete courses
2. **Rate Limiting**: Limit course generation to prevent abuse
3. **Input Validation**: Sanitize course titles, descriptions
4. **Cost Control**: Set max tokens/cost per course generation
5. **Data Privacy**: Separate user progress data, GDPR compliance

---

## Future Enhancements

### Phase 2 Features
- **Course Templates**: Pre-built course structures
- **Collaborative Courses**: Multiple authors
- **Course Marketplace**: Share/discover courses
- **Course Analytics**: Completion rates, difficulty analysis
- **Personalized Courses**: Generate based on user goals
- **Multi-language Courses**: Translation support

### Advanced Features
- **Interactive Elements**: Videos, audio, interactive exercises
- **Gamification**: Badges, achievements, leaderboards
- **Social Learning**: Discussion forums, peer review
- **AI Tutor Integration**: Personalized feedback on exercises
- **Adaptive Difficulty**: Real-time adjustment based on performance

---

## Related Documentation

- [Database Migration Strategy](DATABASE_MIGRATION_STRATEGY.md)
- [Server Capabilities](SERVER_CAPABILITIES_INVENTORY.md)
- [LLM Provider Feature Flags](LLM_PROVIDER_FEATURE_FLAGS.md)
- [Lesson Engine](../app/lesson_engine.py)
- [Diagnostic Engine](../app/diagnostic_engine.py)
- [Learning Path System](../app/path_adaptive.py)

---

## Changelog

**2026-01-12**: Initial architecture design for course modeling feature
