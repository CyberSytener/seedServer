from app.services.path.analytics import NodeAttemptSubmit, UserLearningAnalytics
from app.services.path.adaptive import calculate_mastery_score
from app.api.path import router

print('✅ All analytics imports successful')
print(f'✅ Router prefix: {router.prefix}')
print('✅ Analytics system ready!')


