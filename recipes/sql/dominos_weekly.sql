-- Domino's weekly export for the post-release impact checker
-- One row per week (Monday start), one column per series used in recipes/dominos.yaml.
-- Prefixes: none = UK web, ie_ = Ireland web, app_ = UK app.
--
-- HOW TO USE
-- 1. Edit the THREE settings marked EDIT below: date range (twice) and the item pattern.
-- 2. Run in BigQuery (project clear-destiny-741), save results as CSV, upload to the checker.
--    Pick 'Weekly rows labelled with the Monday the week starts'.
-- 3. Only weekly totals leave BigQuery. No visitor-level data is exported.
--
-- NOTES
-- * Built on CX_Analysis.GA4_Sessions_intraday (one row per session with funnel flags) and
--   CX_Analysis.GA4_items, the same tables the Domino's test queries use.
-- * '..._to_basket' etc. mean the session viewed both pages, not strictly in that order.
-- * Drop the first and last week if they're partial; the checker does this automatically for daily data only.
-- * menu_only_...: sessions that viewed the menu but never the deals page (placebo for deals-page changes).
-- * new_store_select_... columns use FIRST sessions only (ga_session_number = 1), where the
--   store selector comes before the menu/deals pages, so a change on those pages can't affect them.
-- * App = platform 'android'/'ios'; Ireland = country 'IE'; store selector = view_store_select (confirmed by Liam).

WITH sessions AS (
  SELECT DISTINCT
    DATE_TRUNC(CAST(date_key AS DATE), WEEK(MONDAY)) AS week,
    user_pseudo_id, ga_session_id, ga_session_number,
    CASE WHEN country IN ('GB', 'UK') THEN 'UK' WHEN country IN ('IE', 'Ireland') THEN 'IE' ELSE 'other' END AS market,
    CASE WHEN LOWER(platform) = 'web' THEN 'web' WHEN LOWER(platform) IN ('android', 'ios') THEN 'app' ELSE 'other' END AS channel,
    view_home, view_store_select, view_menu, view_deals, view_basket, view_checkout,
    conversion, transaction_id, transaction_value, transaction_delivered,
    transaction_has_voucher
  FROM `clear-destiny-741.CX_Analysis.GA4_Sessions_intraday`
  WHERE date_key BETWEEN '2024-09-02' AND '2026-11-08'          -- EDIT: date range (Monday to Sunday)
    AND ga_session_id IS NOT NULL
),
items AS (
  -- One row per session. Deal line items (item_category 'deal' / 'meal deal' / 'mealdeal') mark a deal
  -- order; they're excluded from item counts, as in the Domino's test queries.
  SELECT
    user_pseudo_id, ga_session_id,
    SUM(IF(LOWER(item_category) NOT IN ('mealdeal', 'meal deal', '(not set)', 'charity', 'delivery charge',
                                        'voucher', 'deal', 'wrapzz', 'wraps'),
           CASE WHEN quantity IS NULL OR quantity = 0 THEN 1 ELSE quantity END, 0)) AS items,
    LOGICAL_OR(LOWER(item_category) IN ('deal', 'meal deal', 'mealdeal')) AS has_deal,
    LOGICAL_OR(LOWER(item_name) LIKE '%big dip%') AS has_item  -- EDIT: item for attach-rate recipes
  FROM `clear-destiny-741.CX_Analysis.GA4_items`
  WHERE date_key BETWEEN '2024-09-02' AND '2026-11-08'          -- EDIT: same date range
  GROUP BY 1, 2
),
s AS (
  SELECT s.*, IFNULL(i.items, 0) AS items, IFNULL(i.has_item, FALSE) AS has_item, IFNULL(i.has_deal, FALSE) AS has_deal
  FROM sessions s
  LEFT JOIN items i USING (user_pseudo_id, ga_session_id)
)
SELECT
  week,
  -- UK web
  COUNT(DISTINCT IF(market = 'UK' AND channel = 'web', CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND view_home = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS home_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND ga_session_number = 1 AND view_store_select = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS new_store_select_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND ga_session_number = 1 AND view_store_select = 1 AND (view_menu = 1 OR view_deals = 1), CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS new_store_select_to_menu_or_deals,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND view_menu = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS menu_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND view_menu = 1 AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS menu_sessions_to_basket,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND view_deals = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS deals_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND view_deals = 1 AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS deals_sessions_to_basket,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND (view_menu = 1 OR view_deals = 1), CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS menu_or_deals_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND (view_menu = 1 OR view_deals = 1) AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS menu_or_deals_sessions_to_basket,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND view_menu = 1 AND IFNULL(view_deals, 0) != 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS menu_only_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND view_menu = 1 AND IFNULL(view_deals, 0) != 1 AND conversion = 1, transaction_id, NULL)) AS menu_only_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS basket_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND view_basket = 1 AND view_checkout = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS basket_sessions_to_checkout,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND view_checkout = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS checkout_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND view_checkout = 1 AND conversion = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS checkout_sessions_to_order,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND conversion = 1, transaction_id, NULL)) AS orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND conversion = 1 AND transaction_delivered = 1, transaction_id, NULL)) AS delivery_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND conversion = 1 AND IFNULL(transaction_delivered, 0) != 1, transaction_id, NULL)) AS collection_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND conversion = 1 AND has_deal, transaction_id, NULL)) AS deal_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND conversion = 1 AND NOT has_deal, transaction_id, NULL)) AS nondeal_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND conversion = 1 AND transaction_has_voucher = 1, transaction_id, NULL)) AS voucher_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND conversion = 1 AND has_item, transaction_id, NULL)) AS orders_with_item,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND conversion = 1 AND has_item AND has_deal, transaction_id, NULL)) AS deal_orders_with_item,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'web') AND conversion = 1 AND has_item AND NOT has_deal, transaction_id, NULL)) AS nondeal_orders_with_item,
  SUM(IF((market = 'UK' AND channel = 'web') AND conversion = 1, transaction_value, 0)) AS revenue,
  SUM(IF((market = 'UK' AND channel = 'web') AND conversion = 1, items, 0)) AS items,
  -- Ireland web
  COUNT(DISTINCT IF(market = 'IE' AND channel = 'web', CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_sessions,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND view_home = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_home_sessions,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND ga_session_number = 1 AND view_store_select = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_new_store_select_sessions,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND ga_session_number = 1 AND view_store_select = 1 AND (view_menu = 1 OR view_deals = 1), CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_new_store_select_to_menu_or_deals,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND view_menu = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_menu_sessions,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND view_menu = 1 AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_menu_sessions_to_basket,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND view_deals = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_deals_sessions,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND view_deals = 1 AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_deals_sessions_to_basket,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND (view_menu = 1 OR view_deals = 1), CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_menu_or_deals_sessions,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND (view_menu = 1 OR view_deals = 1) AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_menu_or_deals_sessions_to_basket,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND view_menu = 1 AND IFNULL(view_deals, 0) != 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_menu_only_sessions,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND view_menu = 1 AND IFNULL(view_deals, 0) != 1 AND conversion = 1, transaction_id, NULL)) AS ie_menu_only_orders,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_basket_sessions,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND view_basket = 1 AND view_checkout = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_basket_sessions_to_checkout,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND view_checkout = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_checkout_sessions,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND view_checkout = 1 AND conversion = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS ie_checkout_sessions_to_order,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND conversion = 1, transaction_id, NULL)) AS ie_orders,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND conversion = 1 AND transaction_delivered = 1, transaction_id, NULL)) AS ie_delivery_orders,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND conversion = 1 AND IFNULL(transaction_delivered, 0) != 1, transaction_id, NULL)) AS ie_collection_orders,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND conversion = 1 AND has_deal, transaction_id, NULL)) AS ie_deal_orders,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND conversion = 1 AND NOT has_deal, transaction_id, NULL)) AS ie_nondeal_orders,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND conversion = 1 AND transaction_has_voucher = 1, transaction_id, NULL)) AS ie_voucher_orders,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND conversion = 1 AND has_item, transaction_id, NULL)) AS ie_orders_with_item,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND conversion = 1 AND has_item AND has_deal, transaction_id, NULL)) AS ie_deal_orders_with_item,
  COUNT(DISTINCT IF((market = 'IE' AND channel = 'web') AND conversion = 1 AND has_item AND NOT has_deal, transaction_id, NULL)) AS ie_nondeal_orders_with_item,
  SUM(IF((market = 'IE' AND channel = 'web') AND conversion = 1, transaction_value, 0)) AS ie_revenue,
  SUM(IF((market = 'IE' AND channel = 'web') AND conversion = 1, items, 0)) AS ie_items,
  -- UK app
  COUNT(DISTINCT IF(market = 'UK' AND channel = 'app', CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND view_home = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_home_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND ga_session_number = 1 AND view_store_select = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_new_store_select_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND ga_session_number = 1 AND view_store_select = 1 AND (view_menu = 1 OR view_deals = 1), CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_new_store_select_to_menu_or_deals,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND view_menu = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_menu_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND view_menu = 1 AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_menu_sessions_to_basket,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND view_deals = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_deals_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND view_deals = 1 AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_deals_sessions_to_basket,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND (view_menu = 1 OR view_deals = 1), CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_menu_or_deals_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND (view_menu = 1 OR view_deals = 1) AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_menu_or_deals_sessions_to_basket,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND view_menu = 1 AND IFNULL(view_deals, 0) != 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_menu_only_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND view_menu = 1 AND IFNULL(view_deals, 0) != 1 AND conversion = 1, transaction_id, NULL)) AS app_menu_only_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND view_basket = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_basket_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND view_basket = 1 AND view_checkout = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_basket_sessions_to_checkout,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND view_checkout = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_checkout_sessions,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND view_checkout = 1 AND conversion = 1, CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)), NULL)) AS app_checkout_sessions_to_order,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND conversion = 1, transaction_id, NULL)) AS app_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND conversion = 1 AND transaction_delivered = 1, transaction_id, NULL)) AS app_delivery_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND conversion = 1 AND IFNULL(transaction_delivered, 0) != 1, transaction_id, NULL)) AS app_collection_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND conversion = 1 AND has_deal, transaction_id, NULL)) AS app_deal_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND conversion = 1 AND NOT has_deal, transaction_id, NULL)) AS app_nondeal_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND conversion = 1 AND transaction_has_voucher = 1, transaction_id, NULL)) AS app_voucher_orders,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND conversion = 1 AND has_item, transaction_id, NULL)) AS app_orders_with_item,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND conversion = 1 AND has_item AND has_deal, transaction_id, NULL)) AS app_deal_orders_with_item,
  COUNT(DISTINCT IF((market = 'UK' AND channel = 'app') AND conversion = 1 AND has_item AND NOT has_deal, transaction_id, NULL)) AS app_nondeal_orders_with_item,
  SUM(IF((market = 'UK' AND channel = 'app') AND conversion = 1, transaction_value, 0)) AS app_revenue,
  SUM(IF((market = 'UK' AND channel = 'app') AND conversion = 1, items, 0)) AS app_items
FROM s
GROUP BY week
ORDER BY week
