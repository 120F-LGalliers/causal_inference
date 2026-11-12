-- Domino's: when did a Monetate experience run, and when did it go to 100%?
--
-- Monetate's APIs don't return experience dates or traffic-split history, but Monetate sends an event to
-- GA4 with experiment_name / experiment_value parameters whenever a visitor is in an experience. This query
-- counts sessions per experience and variant per day, so you can see:
--   * the test period: several variants with similar session counts
--   * the 100% date: from that day, only one variant (or a renamed '100%' / 'LIVE' experience) appears
--   * the end: sessions stop (often the native release, when the Monetate experience is switched off)
--
-- HOW TO USE
-- 1. EDIT the experience name filter and the date range. Keep the range tight (e.g. from the test start to
--    8 weeks after it ended): this reads the raw GA4 event tables, which are large. Use BigQuery's
--    'This query will process X GB' estimate before running.
-- 2. Look at the daily rows (first result) or the summary (switch the final SELECT).
-- Only daily counts leave BigQuery.

WITH exp AS (
  SELECT
    PARSE_DATE('%Y%m%d', event_date) AS day,
    user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS ga_session_id,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'experiment_name') AS exp_name,
    SPLIT((SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'experiment_value'), '-')[SAFE_OFFSET(0)] AS variant
  FROM `clear-destiny-741.analytics_234182913.events_*`
  WHERE _TABLE_SUFFIX BETWEEN '20260519' AND '20260831'        -- EDIT: date range (YYYYMMDD)
    AND LOWER(event_name) LIKE '%monetate%'
    AND LOWER(platform) = 'web'
),
daily AS (
  SELECT day, exp_name, variant, COUNT(DISTINCT CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING))) AS sessions
  FROM exp
  WHERE exp_name IS NOT NULL
    AND LOWER(exp_name) LIKE '%283%'                            -- EDIT: experience name (or remove to list all)
  GROUP BY 1, 2, 3
)
-- Daily view: one row per day, experience and variant, with that variant's share of the experience's sessions.
SELECT
  day, exp_name, variant, sessions,
  ROUND(sessions / SUM(sessions) OVER (PARTITION BY day, exp_name), 3) AS share_of_experience
FROM daily
ORDER BY exp_name, day, variant

-- Summary view: replace the SELECT above with this to get first/last day per experience and variant.
-- SELECT exp_name, variant, MIN(day) AS first_day, MAX(day) AS last_day, SUM(sessions) AS sessions
-- FROM daily GROUP BY 1, 2 ORDER BY exp_name, first_day
