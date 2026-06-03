print('Checking imports...')
from app.api.path import router as path_router
from app.models.path import SeedConstants, UnitBlueprint
from app.services.path.worker import process_path_node_generation

print('✅ All imports successful')
print(f'✅ Router: {path_router.prefix}')
print(f'✅ A2 Topics: {SeedConstants.get_topics_for_level("A2")}')
print('✅ Ready for deployment!')



