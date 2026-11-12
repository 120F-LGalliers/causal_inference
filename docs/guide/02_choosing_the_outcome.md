# Choosing the outcome (and denominator)

The **outcome** is the metric you're checking. The **denominator** (optional, recommended) is the traffic it comes from. Together they make a rate, such as orders per dashboard visit.

## Rule 1: as close to the change as possible

The further a metric is from the change, the more other things affect it, and the smaller the change's share of its ups and downs.

| Change | Close (good) | Far (hard) |
|---|---|---|
| New copy on the login form | Forgotten-username clicks per login page visit | Logins per day |
| New tile on the My Account dashboard | Tile clicks, or new-line orders from dashboard visits | All orders |
| Basket messaging | Basket-to-checkout rate | Revenue |

**Real example:** the Tesco Mobile forgotten-username change was checked on forgotten-username visits per login visit, right next to the change. It came out as *Held* (−23% in the first 8 weeks). The Family Perks tile was checked on orders, several steps away, and came out *Inconclusive*: the data would only have detected an effect of about 20%, and the test found 2.4%.

If the test's primary metric is far from the change (often orders or revenue), consider checking a **closer metric first** (did the behaviour the change targets persist?). Then treat the downstream impact as a separate question.

## Rule 2: use a rate when traffic swings

Counts (orders, clicks) rise and fall with traffic: Black Friday, school holidays, marketing pushes. A rate removes most of that.

- Use a **denominator** that counts the traffic the change could reach: visits to the page where the change lives, or visitors who reached that step.
- Don't use something the change could affect as the denominator. If the change makes more people reach the page, a "per page visit" rate will be distorted.

## Rule 3: match the test's metric definition

Use the same definition as the test's primary metric (same events, same filters), or as close as your analytics allows. If you must use a broader metric, set **"Share of the analysed outcome exposed to the change"** accordingly (see below).

## The "share exposed" setting

If the change only reached part of what you're measuring, the effect gets diluted.

**Example:** the test showed +10% for visitors who saw a new product-page banner. You analyse all orders, but only 40% of orders come from visitors who saw that page. The expected effect in all orders is about 10% × 40% = **+4%**.

The tool uses this to work out the **expected effect if the test held**, which drives the verdict. If you're unsure, analyse a narrower outcome instead (orders from visits that included that page), so the share is close to 100%.

## How much history?

- **Minimum:** 12 weeks before the change. The tool won't run with less.
- **Better:** a year, so the tool sees Black Friday, Christmas and summer at least once.
- **After the change:** at least 8 weeks. Longer post-periods are fine, but the primary window should be no more than about half the history (the app handles this).

## Daily or weekly?

Either. Daily data is summed into Monday-to-Sunday weeks. Weekly data needs you to confirm how weeks are labelled (week starting Monday, starting Sunday, ending Sunday...). The app guesses from the dates and lets you correct it. Getting this wrong shifts everything by up to six days.

## Exporting: a checklist

- [ ] One row per day or week, one column per series, first column the date
- [ ] Outcome, denominator and every candidate control in the same file
- [ ] Same date range for every column
- [ ] No totals or subtotal rows
- [ ] Check for tracking breaks: weeks where a series suddenly drops to near zero or doubles. The app flags these, but it helps to know the cause.

**Client notes**

- **Tesco Mobile (Adobe Analytics):** use the Online virtual report suite. Data starts September 2024. Store-assisted orders have tracking gaps in PROD.
- **Domino's (Monetate):** app-only deals (e.g. Two for Tuesdays) distort app series.
- **Nord Anglia (WTO):** compare schools within the same region, because admissions calendars differ by hemisphere.

Next: [Choosing control series](03_choosing_controls.md)
