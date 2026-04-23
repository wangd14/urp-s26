-- Base demo data for the reviews-digest scenario.
-- A scheduled reporting query reads these core tables.

CREATE TABLE products (
  id SERIAL PRIMARY KEY,
  sku TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  category TEXT NOT NULL
);

CREATE TABLE customer_reviews (
  id SERIAL PRIMARY KEY,
  product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  customer_region TEXT NOT NULL,
  rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  review_text TEXT NOT NULL,
  reviewed_at TIMESTAMPTZ NOT NULL,
  source_channel TEXT NOT NULL DEFAULT 'web'
);

INSERT INTO products (sku, name, category) VALUES
  ('WDG-A', 'Widget Alpha', 'hardware'),
  ('WGT-B', 'Widget Beta', 'hardware'),
  ('SUB-P', 'Plus Subscription', 'service');

INSERT INTO customer_reviews (product_id, customer_region, rating, review_text, reviewed_at, source_channel)
SELECT p.id, r.region, r.rating, r.body, r.reviewed_at, r.source
FROM (
  VALUES
    ('WDG-A', 'US', 5, 'Fast setup and stable performance.', '2026-04-18 14:12:00+00'::timestamptz, 'web'),
    ('WDG-A', 'US', 4, 'Solid value, packaging was damaged.', '2026-04-19 08:05:00+00'::timestamptz, 'mobile'),
    ('WGT-B', 'EU', 2, 'Battery drains in under two hours.', '2026-04-20 17:44:00+00'::timestamptz, 'web'),
    ('WGT-B', 'US', 3, 'Performance okay, app pairing is flaky.', '2026-04-21 11:29:00+00'::timestamptz, 'support_ticket'),
    ('SUB-P', 'US', 5, 'Support team resolved billing in minutes.', '2026-04-22 09:55:00+00'::timestamptz, 'web')
) AS r(sku, region, rating, body, reviewed_at, source)
JOIN products p ON p.sku = r.sku;
