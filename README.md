# l10n-repo

Locale resource files for the Companion app (phone / PC / tablet).

    locales/en.json   source of truth
    locales/fr.json   French
    locales/ja.json   Japanese
    tools/            release helper scripts

Every locale file must contain the same keys as `en.json`, and every
placeholder used in an English string (`{percent}`, `{count}`, `{year}`, ...)
must appear unchanged in the translated string.
