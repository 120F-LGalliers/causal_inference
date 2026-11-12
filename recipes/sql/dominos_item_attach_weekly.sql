-- Domino's: weekly attach rate for ONE item (e.g. stuffed crust, Big Dip), UK web and UK app.
-- A smaller, cheaper version of dominos_weekly.sql for item upsell checks.
--
-- HOW TO USE
-- 1. EDIT the item pattern (matched against item_name, lower case) and the date range (twice).
--    Check the match first with the 'item names' query at the bottom.
-- 2. Run, save as CSV, upload to the checker. Outcome: orders_with_item / orders.
--    Controls: app_orders_with_item / app_orders, nondeal_orders_with_item / nondeal_orders (if relevant).
-- Only weekly totals leave BigQuery.

WITH sessions AS (
  SELECT DISTINCT
    DATE_TRUNC(CAST(date_key AS DATE), WEEK(MONDAY)) AS week,
    user_pseudo_id, ga_session_id, transaction_id,
    CASE WHEN LOWER(platform) = 'web' THEN 'web' WHEN LOWER(platform) IN ('android', 'ios') THEN 'app' END AS channel
  FROM `clear-destiny-741.CX_Analysis.GA4_Sessions_intraday`
  WHERE date_key BETWEEN '2025-01-06' AND '2026-11-08'          -- EDIT: date range (Monday to Sunday)
    AND ga_session_id IS NOT NULL
    AND conversion = 1
    AND country IN ('GB', 'UK')
),
items AS (
  SELECT
    user_pseudo_id, ga_session_id,
    LOGICAL_OR(LOWER(item_category) IN ('deal', 'meal deal', 'mealdeal')) AS has_deal,
    LOGICAL_OR(LOWER(item_name) LIKE '%stuffed%') AS has_item       -- EDIT: item pattern
  FROM `clear-destiny-741.CX_Analysis.GA4_items`
  WHERE date_key BETWEEN '2025-01-06' AND '2026-11-08'          -- EDIT: same date range
  GROUP BY 1, 2
),
s AS (
  SELECT s.*, IFNULL(i.has_item, FALSE) AS has_item, IFNULL(i.has_deal, FALSE) AS has_deal
  FROM sessions s LEFT JOIN items i USING (user_pseudo_id, ga_session_id)
  WHERE channel IS NOT NULL
)
SELECT
  week,
  COUNT(DISTINCT IF(channel = 'web', transaction_id, NULL)) AS orders,
  COUNT(DISTINCT IF(channel = 'web' AND has_item, transaction_id, NULL)) AS orders_with_item,
  COUNT(DISTINCT IF(channel = 'web' AND NOT has_deal, transaction_id, NULL)) AS nondeal_orders,
  COUNT(DISTINCT IF(channel = 'web' AND NOT has_deal AND has_item, transaction_id, NULL)) AS nondeal_orders_with_item,
  COUNT(DISTINCT IF(channel = 'app', transaction_id, NULL)) AS app_orders,
  COUNT(DISTINCT IF(channel = 'app' AND has_item, transaction_id, NULL)) AS app_orders_with_item
FROM s
GROUP BY week
ORDER BY week

-- Item names: run this on its own first to check the pattern catches the right products.
-- SELECT item_name, item_category, COUNT(*) AS n
-- FROM `clear-destiny-741.CX_Analysis.GA4_items`
-- WHERE date_key BETWEEN '2026-10-01' AND '2026-10-07' AND LOWER(item_name) LIKE '%stuffed%'
-- GROUP BY 1, 2 ORDER BY n DESC
