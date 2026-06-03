INSERT INTO storage_item (storage_id, name, quantity, unit, expires_at, metadata) VALUES
  (gen_random_uuid(), 'chicken breast', 500, 'g', '2026-03-27', '{"user_id":"admin","category":"Meat","display_name":"Chicken Breast","canonical_name":"chicken breast"}'),
  (gen_random_uuid(), 'eggs', 12, 'pcs', '2026-04-05', '{"user_id":"admin","category":"Dairy","display_name":"Eggs","canonical_name":"eggs"}'),
  (gen_random_uuid(), 'rice', 1000, 'g', '2026-12-01', '{"user_id":"admin","category":"Staples","display_name":"Rice","canonical_name":"rice"}'),
  (gen_random_uuid(), 'broccoli', 300, 'g', '2026-03-28', '{"user_id":"admin","category":"Vegetables","display_name":"Broccoli","canonical_name":"broccoli"}'),
  (gen_random_uuid(), 'salmon fillet', 400, 'g', '2026-03-26', '{"user_id":"admin","category":"Fish","display_name":"Salmon Fillet","canonical_name":"salmon fillet"}'),
  (gen_random_uuid(), 'pasta', 500, 'g', '2026-10-15', '{"user_id":"admin","category":"Staples","display_name":"Pasta","canonical_name":"pasta"}'),
  (gen_random_uuid(), 'tomato', 4, 'pcs', '2026-03-29', '{"user_id":"admin","category":"Vegetables","display_name":"Tomato","canonical_name":"tomato"}'),
  (gen_random_uuid(), 'olive oil', 500, 'ml', '2027-01-01', '{"user_id":"admin","category":"Staples","display_name":"Olive Oil","canonical_name":"olive oil"}'),
  (gen_random_uuid(), 'spinach', 200, 'g', '2026-03-26', '{"user_id":"admin","category":"Vegetables","display_name":"Spinach","canonical_name":"spinach"}'),
  (gen_random_uuid(), 'cheese', 250, 'g', '2026-04-10', '{"user_id":"admin","category":"Dairy","display_name":"Cheese","canonical_name":"cheese"}'),
  (gen_random_uuid(), 'bell pepper', 3, 'pcs', '2026-03-30', '{"user_id":"admin","category":"Vegetables","display_name":"Bell Pepper","canonical_name":"bell pepper"}'),
  (gen_random_uuid(), 'soy sauce', 200, 'ml', '2027-06-01', '{"user_id":"admin","category":"Staples","display_name":"Soy Sauce","canonical_name":"soy sauce"}')
ON CONFLICT DO NOTHING;
