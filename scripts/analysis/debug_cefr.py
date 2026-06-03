from app.services.diagnostic.session import estimate_cefr_level

tests = [
    (0.2, 2.0, 'A1'),
    (0.45, 2.5, 'A2'),
    (0.6, 3.0, 'B1'),
    (0.75, 3.5, 'B2'),
    (0.9, 4.0, 'C1')
]

for acc, diff, expected in tests:
    result = estimate_cefr_level(acc, diff)
    adjusted = acc * (diff / 3.0)
    print(f'accuracy={acc:.2f}, difficulty={diff:.1f}, adjusted={adjusted:.3f} -> expected={expected}, got={result}, match={result==expected}')

