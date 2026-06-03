from app.core.auth import authenticate
import os
from unittest.mock import Mock
from app.infrastructure.db.sqlite import DB

os.environ['SEED_ADMIN_KEY']='test_admin_key_pytest'
print('env SEED_ADMIN_KEY=', os.environ.get('SEED_ADMIN_KEY'))
request=Mock()
request.headers={'X-Admin-Key':'test_admin_key_pytest'}
request.client=Mock(); request.client.host='127.0.0.1'
request.url=Mock(); request.url.path='/admin'

ctx = authenticate(request, DB(':memory:'))
print('auth_user:', ctx.user_id, 'is_admin=', ctx.is_admin)

