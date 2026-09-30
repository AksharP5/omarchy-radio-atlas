# Map data

`countries.json` is derived from Natural Earth's 1:110m Admin 0 Countries data.
Natural Earth data is in the public domain.

Source: https://www.naturalearthdata.com/

# Country search names

`country-search.json` maps lowercase names and codes to Radio Browser country
codes. It combines Radio Browser's country directory, retrieved on 2026-09-29,
with the labels in `countries.json` and the aliases `USA`, `United States`, `UK`,
and `Great Britain`. Entries without a name or a two-letter code are excluded.
The UI and fetch script share this bundled snapshot, so lookup works offline
without another network request. Update it when country names or codes change.

Source: https://de1.api.radio-browser.info/json/countries
